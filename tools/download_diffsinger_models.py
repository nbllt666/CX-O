"""DiffSinger 预训练模型下载脚本

从 GitHub Releases 下载 vocoder 与 acoustic 模型，支持 ghproxy 加速与断点续传。
用法：
    python download_diffsinger_models.py [--proxy ghproxy|direct] [--only vocoder|acoustic]
"""
import argparse
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# 目标文件清单
ASSETS = [
    {
        "name": "vocoder",
        "url": "https://github.com/openvpi/vocoders/releases/download/pc-nsf-hifigan-44.1k-hop512-128bin-2025.02/pc_nsf_hifigan_44.1k_hop512_128bin_2025.02.zip",
        "dest": "checkpoints/pc_nsf_hifigan_44.1k_hop512_128bin_2025.02.zip",
        "expected_mb": 50.2,
    },
    {
        "name": "acoustic",
        "url": "https://github.com/openvpi/DiffSinger/releases/download/v1.6.0/0211_opencpop_ds1000_keyshift.zip",
        "dest": "checkpoints/0211_opencpop_ds1000_keyshift.zip",
        "expected_mb": 701.5,
    },
]

# 加速代理候选（按优先级排序）
PROXIES = {
    "ghproxy": "https://ghproxy.com/",
    "gh-proxy": "https://gh-proxy.com/",
    "moeyy": "https://github.moeyy.xyz/",
    "mirror.ghproxy": "https://mirror.ghproxy.com/",
    "direct": "",
}


def probe_proxy(proxy_prefix: str, source_url: str, timeout: float = 15.0) -> bool:
    """HEAD 请求检测代理是否可用且能命中目标文件"""
    full_url = proxy_prefix + source_url if proxy_prefix else source_url
    req = urllib.request.Request(full_url, method="HEAD", headers={"User-Agent": "cli"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = resp.status == 200
            size_mb = -1
            cl = resp.headers.get("Content-Length")
            if cl:
                size_mb = round(int(cl) / 1048576, 1)
            print(f"  [probe] {proxy_prefix or 'direct':<20} status={resp.status} size={size_mb}MB")
            return ok
    except Exception as e:
        print(f"  [probe] {proxy_prefix or 'direct':<20} FAIL: {type(e).__name__}: {str(e)[:80]}")
        return False


def pick_available_proxy(source_url: str) -> str:
    """按优先级选择首个可用的代理；都不行则回退直连"""
    print(f"[probe] 检测可用代理 for {source_url.split('/')[-1]}")
    # 先试直连，可能本地网络已可直连 GitHub
    for key, prefix in PROXIES.items():
        if probe_proxy(prefix, source_url):
            print(f"[probe] 选用: {key}")
            return prefix
    print("[probe] 所有代理与直连均失败")
    return ""


def download_with_resume(source_url: str, dest: Path, proxy_prefix: str = "", timeout: float = 120.0) -> bool:
    """带断点续传的下载，返回是否成功"""
    full_url = proxy_prefix + source_url if proxy_prefix else source_url
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    # 已存在的最终文件视为完成
    if dest.is_file():
        print(f"[skip] {dest.name} 已存在 ({dest.stat().st_size/1048576:.1f}MB)")
        return True

    # 断点续传起始位置
    existing = tmp.stat().st_size if tmp.is_file() else 0
    headers = {"User-Agent": "cli"}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        print(f"[resume] 从 {existing/1048576:.1f}MB 处续传 {dest.name}")

    req = urllib.request.Request(full_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = resp.headers.get("Content-Length")
            total = int(total) if total else None
            if existing > 0 and resp.status == 206:
                total = total + existing if total else None
            mode = "ab" if existing > 0 and resp.status == 206 else "wb"
            if mode == "wb":
                existing = 0
            downloaded = existing
            t0 = time.time()
            last_print = t0
            with open(tmp, mode) as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last_print >= 2.0:
                        speed = (downloaded - existing) / max(now - t0, 0.001) / 1024
                        if total:
                            pct = downloaded / total * 100
                            print(f"  [{dest.name}] {downloaded/1048576:.1f}/{total/1048576:.1f}MB ({pct:.1f}%) @ {speed:.0f}KB/s")
                        else:
                            print(f"  [{dest.name}] {downloaded/1048576:.1f}MB @ {speed:.0f}KB/s")
                        last_print = now
            elapsed = time.time() - t0
            print(f"  [{dest.name}] 下载完成，用时 {elapsed:.1f}s，平均 {(downloaded-existing)/max(elapsed,0.001)/1024:.0f}KB/s")
        tmp.replace(dest)
        return True
    except urllib.error.HTTPError as e:
        print(f"  [error] HTTP {e.code}: {e.reason}")
        return False
    except Exception as e:
        print(f"  [error] {type(e).__name__}: {str(e)[:200]}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.set_defaults(proxy=None, only=None)
    ap.add_argument("--proxy", choices=list(PROXIES.keys()), help="指定代理；不指定则自动探测")
    ap.add_argument("--only", choices=["vocoder", "acoustic"], help="只下载指定资产")
    args = ap.parse_args()

    diffsinger_dir = Path(r"C:\CX-O\DiffSinger")
    os.chdir(diffsinger_dir)

    targets = [a for a in ASSETS if not args.only or a["name"] == args.only]

    for asset in targets:
        print(f"\n=== 下载 {asset['name']} (期望 {asset['expected_mb']}MB) ===")
        dest = Path(asset["dest"])

        if args.proxy:
            proxy_prefix = PROXIES[args.proxy]
        else:
            proxy_prefix = pick_available_proxy(asset["url"])

        ok = download_with_resume(asset["url"], dest, proxy_prefix)
        if not ok:
            # 直连或当前代理失败，尝试切换其他代理
            print(f"  [retry] 当前代理失败，尝试其他代理")
            for key, prefix in PROXIES.items():
                if prefix == proxy_prefix:
                    continue
                print(f"  [retry] 尝试 {key}")
                if download_with_resume(asset["url"], dest, prefix):
                    ok = True
                    break
        if ok:
            print(f"[done] {dest.name} -> {dest.stat().st_size/1048576:.1f}MB")
        else:
            print(f"[FAIL] {asset['name']} 下载失败")
            sys.exit(1)

    print("\n全部下载完成")


if __name__ == "__main__":
    main()
