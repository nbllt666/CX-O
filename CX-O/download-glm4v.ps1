# GLM-4V-9B-Flash 模型下载脚本

$MODEL_DIR = "C:\CX-O\CX-O\models\THUDM\glm-4v-9b-flash"
$REPO_ID = "THUDM/glm-4v-9b-flash"
$PYTHON_EXE = "C:\ProgramData\anaconda3\python.exe"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "下载 GLM-4V-9B-Flash 模型 (支持视频)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "模型： $REPO_ID" -ForegroundColor Yellow
Write-Host "保存路径： $MODEL_DIR" -ForegroundColor Yellow
Write-Host ""
Write-Host "特性:" -ForegroundColor Green
Write-Host "  - 支持图片理解"
Write-Host "  - 支持视频理解 (自动抽帧)"
Write-Host "  - Flash 版本，推理速度更快"
Write-Host "  - 最大上下文：16K tokens"
Write-Host ""
Write-Host "提示：模型约 8GB，使用官方 HuggingFace 下载" -ForegroundColor Yellow
Write-Host ""

# 创建目录
New-Item -ItemType Directory -Path $MODEL_DIR -Force | Out-Null

# 设置环境变量
$env:HF_ENDPOINT = "https://huggingface.co"
$env:HF_HOME = $MODEL_DIR

Write-Host "开始下载..." -ForegroundColor Cyan
Write-Host ""

# 执行 Python 下载
& $PYTHON_EXE -c @"
import os
os.environ['HF_ENDPOINT'] = 'https://huggingface.co'
os.environ['HF_HOME'] = r'$MODEL_DIR'

from huggingface_hub import snapshot_download

print(f'存储路径：{os.environ.get("HF_HOME")}')
print()

try:
    snapshot_download(
        repo_id='$REPO_ID',
        local_dir=os.environ['HF_HOME']
    )
    print()
    print('模型下载完成！')
except Exception as e:
    print(f'下载失败：{e}')
    import traceback
    traceback.print_exc()
"@

Write-Host ""
Write-Host "按回车键退出..." -ForegroundColor Gray
Read-Host
