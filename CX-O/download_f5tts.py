import os
import sys

conda_python = r"C:\ProgramData\anaconda3\python.exe"
if not os.path.exists(conda_python):
    print(f"错误: 找不到 Python at {conda_python}")
    print("请确保 Anaconda 已正确安装")
    input("按回车键退出...")
    sys.exit(1)

os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HOME'] = r'C:\CX-O\CX-O\F5-TTS\hf_download'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '1'

from huggingface_hub import snapshot_download

print('=' * 50)
print('下载 F5-TTS 模型')
print('=' * 50)
print(f'HF_ENDPOINT: {os.environ.get("HF_ENDPOINT")}')
print(f'HF_HOME: {os.environ.get("HF_HOME")}')
print()

try:
    snapshot_download(
        repo_id='SWivid/E2-TTS-Base',
        cache_dir=os.environ['HF_HOME']
    )
    print()
    print('F5-TTS 模型下载完成！')
except Exception as e:
    print(f'下载失败: {e}')

print()
input("按回车键退出...")
