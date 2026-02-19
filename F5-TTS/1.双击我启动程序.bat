@echo off

SET CONDA_PATH=.\Miniconda3

REM 激活base环境
CALL %CONDA_PATH%\Scripts\activate.bat %CONDA_PATH%

set HF_ENDPOINT=https://hf-mirror.com
set HF_HOME=%CD%\hf_download

python gradio_app.py --port 8080

cmd /k