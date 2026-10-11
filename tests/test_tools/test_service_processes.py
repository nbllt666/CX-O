"""Launcher ownership tests: no real service is spawned or terminated."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("service_processes", _ROOT / "tools/service_processes.py")
launcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launcher)


class Process:
    def __init__(self, pid, created, command, children=()):
        self.pid = pid
        self.created = created
        self.command = command
        self.descendants = list(children)
        self.terminated = False

    def create_time(self):
        return self.created

    def cmdline(self):
        return self.command

    def is_running(self):
        return not self.terminated

    def children(self, recursive=False):
        return self.descendants

    def terminate(self):
        self.terminated = True

    kill = terminate


@pytest.fixture
def environment(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    root = tmp_path / "repository with spaces"
    (root / "logs").mkdir(parents=True)
    script = root / "CX-O-SERVER/start.bat"
    script.parent.mkdir()
    script.write_text("@echo off\n", encoding="utf-8")
    path = root / "logs/service-processes.json"
    child = Process(101, 12, ["python.exe"])
    proc = Process(100, 11, ["cmd.exe", "/d", "/s", "/c", str(script)], [child])
    record = {"service": "server", "pid": proc.pid, "created": 11, "command": proc.command}
    monkeypatch.setattr(launcher.psutil, "Process", lambda pid: proc)
    monkeypatch.setattr(launcher.psutil, "wait_procs", lambda processes, timeout: (processes, []))

    @contextmanager
    def lock(_root):
        yield path

    monkeypatch.setattr(launcher, "manifest_lock", lock)
    return root, path, proc, child, record


@pytest.mark.parametrize("changed", ["created", "command", "script", "exited"])
def test_changed_identity_is_never_stopped(environment, changed):
    root, path, proc, child, record = environment
    if changed == "created":
        proc.created += 1
    elif changed == "command":
        proc.command = ["cmd.exe", "unrelated.bat"]
    elif changed == "script":
        record["command"] = ["cmd.exe", "C:/another-project/start.bat"]
    else:
        proc.terminated = True
    launcher.save_records(path, root, [record])
    assert launcher.stop_services(root)
    assert not child.terminated
    if changed != "exited":
        assert not proc.terminated


def test_matching_identity_stops_only_its_tree(environment):
    root, path, proc, child, record = environment
    unrelated = Process(102, 12, ["python.exe"])
    launcher.save_records(path, root, [record])
    assert launcher.stop_services(root)
    assert proc.terminated and child.terminated
    assert not unrelated.terminated
    assert launcher.load_records(path, root) == []


def test_occupied_port_is_not_adopted_or_launched(environment, monkeypatch):
    root, path, proc, child, _ = environment
    monkeypatch.setattr(launcher, "listeners", lambda port: {999})
    monkeypatch.setattr(launcher.psutil, "Popen", lambda *a, **kw: pytest.fail("must not spawn"))
    assert not launcher.start_service("server", root)
    assert not path.exists()
    assert not proc.terminated and not child.terminated


def test_slow_start_is_recorded_and_can_be_stopped(environment, monkeypatch):
    root, path, proc, child, _ = environment
    calls = []
    monkeypatch.setattr(launcher, "listeners", lambda port: set())

    def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return proc

    monkeypatch.setattr(launcher.psutil, "Popen", spawn)
    assert not launcher.start_service("server", root, timeout=0)
    assert launcher.load_records(path, root)[0]["created"] == 11
    assert calls[0][1]["creationflags"] == launcher.subprocess.CREATE_NO_WINDOW
    assert '"' + str(root / "CX-O-SERVER/start.bat") + '"' in calls[0][0][0]
    assert launcher.stop_services(root)
    assert proc.terminated and child.terminated


def test_failed_stop_keeps_manifest(environment, monkeypatch):
    root, path, _, _, record = environment
    launcher.save_records(path, root, [record])

    def deny(_process):
        raise launcher.psutil.AccessDenied(100)

    monkeypatch.setattr(launcher, "stop_tree", deny)
    assert not launcher.stop_services(root)
    assert launcher.load_records(path, root) == [record]


@pytest.mark.parametrize("ready", [False, True])
def test_repeated_start_rechecks_readiness_without_respawning(environment, monkeypatch, ready):
    root, path, proc, child, record = environment
    launcher.save_records(path, root, [record])
    checks = []

    def ports(port):
        checks.append(port)
        return {child.pid} if ready else set()

    monkeypatch.setattr(launcher, "listeners", ports)
    monkeypatch.setattr(launcher.psutil, "Popen", lambda *a, **kw: pytest.fail("must not respawn"))
    assert launcher.start_service("server", root, timeout=0.01) is ready
    assert checks == [8000]
    assert launcher.load_records(path, root) == [record]


@pytest.mark.parametrize("data", [[100], {"version": 1, "root": "wrong", "records": []}])
def test_untrusted_manifest_fails_closed(environment, data):
    root, path, proc, child, _ = environment
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        launcher.stop_services(root)
    assert not proc.terminated and not child.terminated
