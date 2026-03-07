import subprocess
import sys
import time
import os

processes = []

def start_service(name, cwd, cmd):
    print(f"Starting {name}...", file=sys.stderr)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        processes.append((name, proc))
        print(f"✓ {name} started (PID: {proc.pid})", file=sys.stderr)
        return proc
    except Exception as e:
        print(f"✗ Failed to start {name}: {e}", file=sys.stderr)
        return None

os.chdir(r"d:\CX-O")

start_service("CXHMS", r"d:\CX-O\CXHMS", "python main.py")
time.sleep(3)

start_service("Gateway", r"d:\CX-O\cx-o-gateway", "python main.py")
time.sleep(3)

start_service("ASR", r"d:\CX-O\SenseVoice", "python api.py")
time.sleep(3)

print("\n" + "="*50, file=sys.stderr)
print("Checking services...", file=sys.stderr)
print("="*50, file=sys.stderr)

for name, proc in processes:
    if proc.poll() is None:
        print(f"✓ {name} is running (PID: {proc.pid})", file=sys.stderr)
    else:
        stdout, stderr = proc.communicate()
        print(f"✗ {name} exited with code {proc.returncode}", file=sys.stderr)
        if stderr:
            print(f"Error: {stderr[:500]}", file=sys.stderr)

print("\nServices started. Press Ctrl+C to stop.", file=sys.stderr)

try:
    while True:
        time.sleep(1)
        for name, proc in processes:
            if proc.poll() is not None:
                print(f"⚠ {name} has stopped!", file=sys.stderr)
except KeyboardInterrupt:
    print("\nStopping services...", file=sys.stderr)
    for name, proc in processes:
        proc.terminate()
    print("Done.", file=sys.stderr)
