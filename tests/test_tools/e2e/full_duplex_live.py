import asyncio, base64, json, time, wave
import numpy as np
WS_URL="ws://127.0.0.1:8000/api/ws/default"
AUDIO=r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\ref_034ed0259d8043db.wav"
def load_16k():
    with wave.open(AUDIO,"rb") as wf:
        sr=wf.getframerate();ch=wf.getnchannels();sw=wf.getsampwidth();fr=wf.readframes(wf.getnframes())
    d=np.frombuffer(fr,dtype=np.int16).astype(np.float32)/32768.0
    if ch>1: d=d.reshape(-1,ch).mean(axis=1)
    if sr!=16000:
        n=int(len(d)*16000/sr); d=np.interp(np.linspace(0,len(d)-1,n),np.arange(len(d)),d).astype(np.float32)
    return d
async def main():
    import websockets
    pcm=(np.clip(load_16k(),-1,1)*32767).astype(np.int16)
    t0=None; st={"partial":0,"prefill":0,"tts_audio_bytes":0,"tts_chunks":0,"final":0,"speaker":None,"err":0}
    tts_first=None
    async with websockets.connect(WS_URL,max_size=None) as ws:
        await ws.send(json.dumps({"action":"voice.dual_stream","request_id":"fd-live","data":{"init":True,"agent_id":"default"}}))
        await asyncio.sleep(0.25)
        async def rcv():
            while True:
                m=json.loads(await asyncio.wait_for(ws.recv(),timeout=40))
                k=m.get("type") or m.get("action") or ""
                now=time.monotonic()
                if k=="voice.partial":
                    st["partial"]+=1
                    d=m.get("data",{}) or {}
                    if d.get("speaker_name"): st["speaker"]=d["speaker_name"]
                elif "prefill" in k: st["prefill"]+=1
                elif k in ("stream","voice.tts_chunk"):
                    d=m.get("data",{}) or {}
                    b=d.get("audio_data") or ""
                    if b:
                        st["tts_chunks"]+=1; st["tts_audio_bytes"]+=len(b)
                        if tts_first is None and t0: tts_first=(now-t0)*1000
                elif k=="error": st["err"]+=1
                elif m.get("is_final") is True: st["final"]+=1
        rt=asyncio.create_task(rcv())
        step=960; t0=time.monotonic()
        for pos in range(0,len(pcm),step):
            await ws.send(json.dumps({"action":"voice.dual_stream","request_id":"fd-live","data":{"audio":base64.b64encode(pcm[pos:pos+step].tobytes()).decode("ascii"),"sample_rate":16000}}))
            await asyncio.sleep(0.03)
        for _ in range(20):
            await ws.send(json.dumps({"action":"voice.dual_stream","request_id":"fd-live","data":{"audio":base64.b64encode(b"\x00"*1920).decode("ascii"),"sample_rate":16000}}))
            await asyncio.sleep(0.03)
        await asyncio.sleep(14.0)
        rt.cancel()
    ok = st["partial"]>0 and st["prefill"]>0 and st["tts_chunks"]>0 and st["tts_audio_bytes"]>0
    print(f"== 全双工 {'ACTIVE' if ok else '异常'} ==")
    print(f"   voice.partial={st['partial']}  prefill_started={st['prefill']}  final={st['final']}  error={st['err']}")
    print(f"   TTS 音频块={st['tts_chunks']}  音频字节={st['tts_audio_bytes']}  首块T5≈{tts_first and round(tts_first,0)}ms(推完测得)")
    print(f"   说话人标签={st['speaker'] or '(未命中注册音频)'}")
asyncio.run(main())
