"""临时分析 .ds 文件结构，用于 score→.ds 转换开发。分析完毕可删除。"""
import json
import sys
from pathlib import Path

ds_path = Path(r"C:\CX-O\DiffSinger\samples\00_我多想说再见啊.ds")
data = json.load(open(ds_path, "r", encoding="utf-8"))
print(f"type: {type(data).__name__}, len: {len(data)}")
print(f"top-level keys (element 0):")
e = data[0]
for k, v in e.items():
    if isinstance(v, str):
        preview = v[:150]
        print(f"  {k}: str len={len(v)}  preview={preview!r}")
    elif isinstance(v, list):
        print(f"  {k}: list len={len(v)}  preview={str(v[:8])[:150]}")
    else:
        print(f"  {k}: {type(v).__name__}  value={v!r}")

# 第二个元素对比
print(f"\nelement 1 keys: {list(data[1].keys())}")
print(f"element 1 text: {data[1].get('text')!r}")
print(f"element 1 offset: {data[1].get('offset')!r}")

# 看 ph_seq / note_seq / f0_seq 的对应关系
e0 = data[0]
print(f"\n=== element 0 对应关系 ===")
print(f"text: {e0['text']}")
print(f"ph_seq: {e0['ph_seq']}")
print(f"ph_num: {e0.get('ph_num')}")
print(f"note_seq: {e0['note_seq']}")
print(f"note_dur: {e0.get('note_dur')}")
print(f"note_slur: {e0.get('note_slur')}")
print(f"f0_timestep: {e0.get('f0_timestep')}")
f0 = e0.get("f0_seq", "")
f0_list = [float(x) for x in f0.split()] if f0 else []
print(f"f0_seq: len={len(f0_list)}, first 10={f0_list[:10]}")
print(f"offset: {e0.get('offset')}")
