"""Start and stop only service trees created by this repository's launcher."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time

import psutil


ROOT = Path(__file__).resolve().parent.parent
SERVICES = {
    "server": ("CX-O-SERVER", 8000, []),
    "voice": ("CX-O-VoiceWorkStation", 8200, []),
    "model": ("CXO-ModelStation", 8300, []),
    "frontend": ("APP-Frontend", 3100, ["browser"]),
}
_STARTED = time.monotonic()


def log(message: str, error: bool = False) -> None:
    """Print launcher diagnostics without command/environment contents."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
          f"[{'ERROR' if error else 'INFO'}] [{time.monotonic() - _STARTED:.2f}s] {message}")


@contextmanager
def manifest_lock(root: Path):
    """Serialize separate start/stop invocations using a Windows file lock."""
    import msvcrt

    directory = root / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "service-processes.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + 10
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Another launcher operation is still running")
                time.sleep(0.1)
        try:
            yield directory / "service-processes.json"
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def load_records(path: Path, root: Path) -> list[dict]:
    """Reject corrupt or foreign manifests; never adopt legacy bare PID files."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("version") != 1
            or data.get("root") != str(root) or not isinstance(data.get("records"), list)
            or any(not isinstance(record, dict) for record in data["records"])):
        raise ValueError("Invalid service manifest; no process was adopted")
    return data["records"]


def save_records(path: Path, root: Path, records: list[dict]) -> None:
    """Publish a complete manifest atomically while holding manifest_lock."""
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps({"version": 1, "root": str(root), "records": records}),
                             encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def verified_process(record: dict, root: Path):
    """Require PID, birth time and exact command identity before managing a process."""
    if not isinstance(record, dict) or record.get("service") not in SERVICES:
        return None
    command = record.get("command")
    script = str(root / SERVICES[record["service"]][0] / "start.bat")
    if (not isinstance(command, list) or not all(isinstance(s, str) for s in command)
            or script.casefold() not in " ".join(command).casefold()
            or not isinstance(record.get("pid"), int) or record["pid"] <= 0
            or not isinstance(record.get("created"), (int, float))):
        return None
    try:
        process = psutil.Process(record["pid"])
        if (process.create_time() == record["created"] and process.cmdline() == command
                and process.is_running()):
            return process
    except psutil.NoSuchProcess:
        return None
    # AccessDenied propagates: retain the record for a later stop attempt.
    return None


def listeners(port: int) -> set[int]:
    """Check all local TCP listeners, including IPv6 and non-loopback binds."""
    return {c.pid for c in psutil.net_connections(kind="tcp")
            if c.status == psutil.CONN_LISTEN and c.laddr.port == port and c.pid is not None}


def stop_tree(process) -> None:
    """Stop the verified root and its current descendants using psutil identity checks."""
    children = process.children(recursive=True)
    targets = list(reversed(children)) + [process]
    for target in targets:
        try:
            target.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(targets, timeout=5)
    for target in alive:
        try:
            target.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=5)
    if alive:
        raise RuntimeError("Some owned service processes could not be stopped")


def start_service(service: str, root: Path, timeout: float = 30) -> bool:
    """Register the process we spawn before waiting; ports never establish ownership."""
    directory, port, arguments = SERVICES[service]
    script = root / directory / "start.bat"
    if not script.is_file():
        raise FileNotFoundError(script)
    with manifest_lock(root) as path:
        records = load_records(path, root)
        record = next((r for r in records if r.get("service") == service
                       and verified_process(r, root) is not None), None)
        if record is not None:
            log(f"{service}: rechecking existing launcher readiness")
        else:
            if listeners(port):
                log(f"{service}: port {port} is already occupied; existing process left unmanaged", True)
                return False
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            suffix = " " + " ".join(arguments) if arguments else ""
            command = f'"{comspec}" /d /s /c ""{script}"{suffix}"'
            with (root / "logs" / f"{service}-launcher.log").open("ab") as output:
                process = psutil.Popen(
                    command, cwd=str(script.parent), stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            try:
                record = {"service": service, "pid": process.pid,
                          "created": process.create_time(), "command": process.cmdline()}
                records = [r for r in records if r.get("service") != service]
                save_records(path, root, [*records, record])
            except BaseException:
                stop_tree(process)
                raise

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        owned = verified_process(record, root)
        if owned is None:
            break
        try:
            family = {owned.pid, *(child.pid for child in owned.children(recursive=True))}
        except psutil.NoSuchProcess:
            break
        if listeners(port) & family:
            log(f"{service}: ready on port {port}")
            return True
        time.sleep(0.25)
    log(f"{service}: not ready; see logs/{service}-launcher.log. Owned process remains recorded.", True)
    return False


def stop_services(root: Path) -> bool:
    """Preserve failed stop records; discard exited/reused identities without killing them."""
    success = True
    with manifest_lock(root) as path:
        records = load_records(path, root)
        remaining = []
        for record in records:
            try:
                process = verified_process(record, root)
                if process is None:
                    log("Skipping exited or changed process identity")
                    continue
                stop_tree(process)
                log(f"{record['service']}: stopped owned process tree")
            except (psutil.Error, OSError, RuntimeError) as exc:
                remaining.append(record)
                success = False
                log(f"Unable to stop owned process ({type(exc).__name__}); record retained", True)
        save_records(path, root, remaining)
    return success


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    parser.add_argument("service", choices=list(SERVICES), nargs="?")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This launcher is for Windows batch entry points")
    if args.action == "start" and args.service is None:
        parser.error("start requires a service")
    try:
        return 0 if (start_service(args.service, ROOT) if args.action == "start"
                     else stop_services(ROOT)) else 1
    except (OSError, ValueError, psutil.Error, RuntimeError) as exc:
        log(f"Launcher failed ({type(exc).__name__}); inspect service logs and manifest", True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
