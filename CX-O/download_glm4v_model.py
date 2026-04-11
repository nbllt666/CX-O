import os

MODEL_DIR = r"C:\CX-O\CX-O\models\THUDM\glm-4v-9b"
REPO_ID = "THUDM/glm-4v-9b"

os.environ['HF_ENDPOINT'] = 'https://huggingface.co'
os.environ['HF_HOME'] = MODEL_DIR

from huggingface_hub import snapshot_download

print('=' * 50)
print('下载 GLM-4V-9B 模型 (支持视频)')
print('=' * 50)
print(f'模型： {REPO_ID}')
print(f'存储路径： {MODEL_DIR}')
print()
print('注意：模型约 18GB，下载需要 30-60 分钟')
print('请耐心等待，不要关闭此窗口')
print()

try:
    print('开始下载...')
    snapshot_download(
        repo_id=REPO_ID,
        local_dir=MODEL_DIR,
        local_dir_use_symlinks=False,
        max_workers=4
    )
    print()
    print('=' * 50)
    print('模型下载完成！')
    print('=' * 50)
except Exception as e:
    print(f'下载失败： {e}')
    import traceback
    traceback.print_exc()

print()
input("按回车键退出...")
