/**
 * PCM 编码纯函数：Float32 采样 → Int16 PCM（Live WS 上行协议格式）。
 *
 * 协议决策（对齐 CX-O-SERVER server/services/vad_processor.py）：
 * - 服务端以 np.frombuffer(audio_data, dtype=np.int16) @ sample_rate=16000 读取
 *   Live WebSocket（/ws/live）二进制帧，故上行必须为裸 Int16 PCM 小端字节流；
 * - 增益在编码前应用于 float 域，随后 clamp 到 [-1, 1] 再量化，
 *   避免增益放大导致的 Int16 溢出回绕。
 */

/** Float32 采样 → Int16 PCM，增益在量化前应用并钳制 */
export function encodePcm16(input: Float32Array, gain: number): Int16Array<ArrayBuffer> {
  const g = Number.isFinite(gain) ? gain : 1;
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i] * g));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

/** 时域 RMS 音量（0~1）：VAD 本地方差的兜底/调试用途 */
export function computeRmsVolume(input: Float32Array, gain: number): number {
  if (input.length === 0) return 0;
  const g = Number.isFinite(gain) ? gain : 1;
  let sum = 0;
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i] * g));
    sum += s * s;
  }
  return Math.min(Math.sqrt(sum / input.length), 1);
}
