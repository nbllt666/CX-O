"""精确比对 warmup_test.py 的 FULL_SYSTEM 与 default agent system_prompt。"""
import difflib
import sys

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")
from server.chat_helpers import get_agent_config

real = (get_agent_config("default") or {}).get("system_prompt", "").strip()
src = open("docker/llm/warmup_test.py", encoding="utf-8").read()
full = src.split('FULL_SYSTEM = """', 1)[1].split('"""', 1)[0]

print(f"real len={len(real)}  full len={len(full)}  equal={real == full}")
print()
if real != full:
    print("=== 逐行差异（- real, + full）===")
    diff = difflib.ndiff(real.split("\n"), full.split("\n"))
    shown = 0
    for line in diff:
        if line[0] in "+-":
            print(repr(line))
            shown += 1
            if shown >= 30:
                print("... (截断)")
                break
