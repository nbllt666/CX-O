# -*- coding: utf-8 -*-
"""
CosyVoice Model Download Script
"""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

print("=" * 50)
print("Downloading CosyVoice models...")
print("=" * 50)

try:
    from modelscope import snapshot_download
    print("Using ModelScope SDK...")
    
    models = [
        ('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', 'pretrained_models/Fun-CosyVoice3-0.5B'),
        ('iic/CosyVoice2-0.5B', 'pretrained_models/CosyVoice2-0.5B'),
        ('iic/CosyVoice-300M', 'pretrained_models/CosyVoice-300M'),
        ('iic/CosyVoice-300M-SFT', 'pretrained_models/CosyVoice-300M-SFT'),
        ('iic/CosyVoice-300M-Instruct', 'pretrained_models/CosyVoice-300M-Instruct'),
        ('iic/CosyVoice-ttsfrd', 'pretrained_models/CosyVoice-ttsfrd'),
    ]
    
    for model_id, local_dir in models:
        print(f"\nDownloading {model_id} -> {local_dir}...")
        try:
            snapshot_download(model_id, local_dir=local_dir)
            print(f"Successfully downloaded {model_id}")
        except Exception as e:
            print(f"Failed to download {model_id}: {e}")
            continue
    
except ImportError:
    print("ModelScope SDK not found, trying HuggingFace...")
    try:
        from huggingface_hub import snapshot_download as hf_download
        
        models = [
            ('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', 'pretrained_models/Fun-CosyVoice3-0.5B'),
            ('FunAudioLLM/CosyVoice2-0.5B', 'pretrained_models/CosyVoice2-0.5B'),
            ('FunAudioLLM/CosyVoice-300M', 'pretrained_models/CosyVoice-300M'),
            ('FunAudioLLM/CosyVoice-300M-SFT', 'pretrained_models/CosyVoice-300M-SFT'),
            ('FunAudioLLM/CosyVoice-300M-Instruct', 'pretrained_models/CosyVoice-300M-Instruct'),
            ('FunAudioLLM/CosyVoice-ttsfrd', 'pretrained_models/CosyVoice-ttsfrd'),
        ]
        
        for model_id, local_dir in models:
            print(f"\nDownloading {model_id} -> {local_dir}...")
            try:
                hf_download(model_id, local_dir=local_dir)
                print(f"Successfully downloaded {model_id}")
            except Exception as e:
                print(f"Failed to download {model_id}: {e}")
                continue
                
    except ImportError:
        print("ERROR: Neither ModelScope nor HuggingFace SDK found!")
        print("Please install: pip install modelscope")
        sys.exit(1)

print("\n" + "=" * 50)
print("Model download completed!")
print("=" * 50)
