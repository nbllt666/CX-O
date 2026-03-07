import time
import httpx
import argparse
import json
from pathlib import Path


def run_benchmark(url: str, audio_path: str, ref_text: str, target_text: str, ref_wav_len: int, iterations: int = 5):
    with open(audio_path, 'rb') as f:
        audio_data = f.read()
    
    results = []
    
    print(f"Running {iterations} iterations...")
    print("=" * 70)
    print(f"{'Test':<6} {'TTFB(s)':<10} {'Total(s)':<10} {'Audio(s)':<10} {'RTF':<10}")
    print("=" * 70)
    
    for i in range(iterations):
        start_time = time.time()
        
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                url,
                files={'reference_wav': ('test.wav', audio_data, 'audio/wav')},
                data={
                    'reference_wav_len': str(ref_wav_len),
                    'reference_text': ref_text,
                    'target_text': target_text,
                }
            )
        
        total_time = time.time() - start_time
        
        if response.status_code == 200:
            audio_len = len(response.content) / 4 / 24000
            ttfb = float(response.headers.get('X-TTFB', '0'))
            inference_time = float(response.headers.get('X-Inference-Time', '0'))
            rtf = total_time / audio_len
            
            print(f"{i+1:<6} {ttfb:<10.3f} {total_time:<10.3f} {audio_len:<10.3f} {rtf:<10.3f}")
            
            results.append({
                'iteration': i + 1,
                'ttfb': ttfb,
                'total_time': total_time,
                'inference_time': inference_time,
                'audio_length': audio_len,
                'rtf': rtf,
            })
        else:
            print(f"{i+1:<6} FAILED: {response.status_code} - {response.text[:100]}")
    
    print("=" * 70)
    
    if results:
        avg_ttfb = sum(r['ttfb'] for r in results) / len(results)
        avg_total = sum(r['total_time'] for r in results) / len(results)
        avg_inference = sum(r['inference_time'] for r in results) / len(results)
        avg_rtf = sum(r['rtf'] for r in results) / len(results)
        
        print(f"\n{'Average':<6} {avg_ttfb:<10.3f} {avg_total:<10.3f} {'-':<10} {avg_rtf:<10.3f}")
        print(f"\nPerformance Summary:")
        print(f"  - Average TTFB (首包延迟): {avg_ttfb:.3f}s")
        print(f"  - Average Total Time: {avg_total:.3f}s")
        print(f"  - Average Inference Time: {avg_inference:.3f}s")
        print(f"  - Average RTF: {avg_rtf:.3f}x ({1/avg_rtf:.1f}x realtime)")
        
        return {
            'avg_ttfb': avg_ttfb,
            'avg_total_time': avg_total,
            'avg_inference_time': avg_inference,
            'avg_rtf': avg_rtf,
            'iterations': len(results),
        }
    
    return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='F5-TTS Performance Benchmark')
    parser.add_argument('--url', type=str, default='http://localhost:8000/v2/models/f5_tts/infer')
    parser.add_argument('--audio', type=str, default='test.wav')
    parser.add_argument('--ref-text', type=str, default='你好')
    parser.add_argument('--target-text', type=str, default='这是一个测试文本，用于测量推理性能和首包延迟')
    parser.add_argument('--ref-wav-len', type=int, default=48000)
    parser.add_argument('--iterations', type=int, default=5)
    
    args = parser.parse_args()
    
    result = run_benchmark(
        url=args.url,
        audio_path=args.audio,
        ref_text=args.ref_text,
        target_text=args.target_text,
        ref_wav_len=args.ref_wav_len,
        iterations=args.iterations,
    )
    
    if result:
        with open('benchmark_results.json', 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nResults saved to benchmark_results.json")
