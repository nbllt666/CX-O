import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HOME'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'F5-TTS', 'hf_download')
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '1'

from huggingface_hub import snapshot_download

print("Downloading F5-TTS model...")
print(f"HF_ENDPOINT: {os.environ.get('HF_ENDPOINT')}")
print(f"HF_HOME: {os.environ.get('HF_HOME')}")

try:
    snapshot_download(
        repo_id='SWivid/E2-TTS-Base',
        cache_dir=os.environ['HF_HOME']
    )
    print("F5-TTS model downloaded successfully!")
except Exception as e:
    print(f"Error downloading model: {e}")
