import { Button, Card, CardBody } from '../../../components/ui';
import {
  AudioConfig,
  AudioFile,
  VadConfig,
  SensevoiceStreamingConfig,
  AdaptivePollingConfig,
  AdaptivePollingStats,
  FirewallV3Config,
  VoiceWorkstationStatus,
  SaveStatus,
} from '../types';

export interface AudioCardProps {
  audioFiles: AudioFile[];
  uploadingFile: boolean;
  onAudioUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  playingAudio: string | null;
  onPlayingAudioChange: (name: string | null) => void;
  onPlayAudio: (name: string) => void;
  onDeleteAudio: (name: string) => void;
  audioFileUrl: (name: string) => string;
  voiceWorkstationStatus: VoiceWorkstationStatus;
  audioConfig: AudioConfig;
  onAudioConfigChange: (config: AudioConfig) => void;
  speedMax: number;
  vadConfig: VadConfig;
  onVadConfigChange: (config: VadConfig) => void;
  sensevoiceStreamingConfig: SensevoiceStreamingConfig;
  onSensevoiceStreamingConfigChange: (config: SensevoiceStreamingConfig) => void;
  adaptivePollingConfig: AdaptivePollingConfig;
  onAdaptivePollingConfigChange: (config: AdaptivePollingConfig) => void;
  adaptivePollingStats: AdaptivePollingStats;
  firewallV3Config: FirewallV3Config;
  onFirewallV3ConfigChange: (config: FirewallV3Config) => void;
  onSave: () => void;
  saveStatus: SaveStatus;
}

export function AudioCard(props: AudioCardProps) {
  const {
    audioFiles,
    uploadingFile,
    onAudioUploadChange,
    playingAudio,
    onPlayingAudioChange,
    onPlayAudio,
    onDeleteAudio,
    audioFileUrl,
    voiceWorkstationStatus,
    audioConfig,
    onAudioConfigChange,
    speedMax,
    vadConfig,
    onVadConfigChange,
    sensevoiceStreamingConfig,
    onSensevoiceStreamingConfigChange,
    adaptivePollingConfig,
    onAdaptivePollingConfigChange,
    adaptivePollingStats,
    firewallV3Config,
    onFirewallV3ConfigChange,
    onSave,
    saveStatus,
  } = props;

  return (
    <div className="space-y-6">
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">音频文件管理</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            上传参考音频文件，用于 TTS 语音克隆
          </p>
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 px-4 py-2 bg-[var(--color-accent)] text-white rounded-[var(--radius-md)] cursor-pointer hover:opacity-90">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                <span>{uploadingFile ? '上传中...' : '上传音频'}</span>
                <input
                  type="file"
                  accept=".wav,.mp3,.ogg,.flac"
                  onChange={onAudioUploadChange}
                  disabled={uploadingFile}
                  className="hidden"
                />
              </label>
              <span className="text-sm text-[var(--color-text-tertiary)]">
                支持 WAV, MP3, OGG, FLAC 格式
              </span>
            </div>

            {audioFiles.length > 0 && (
              <div className="border border-[var(--color-border)] rounded-[var(--radius-md)] overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-[var(--color-bg-tertiary)]">
                    <tr>
                      <th className="px-4 py-2 text-left">文件名</th>
                      <th className="px-4 py-2 text-left">大小</th>
                      <th className="px-4 py-2 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {audioFiles.map((file) => (
                      <tr key={file.name} className="border-t border-[var(--color-border)]">
                        <td className="px-4 py-2">{file.name}</td>
                        <td className="px-4 py-2 text-[var(--color-text-secondary)]">
                          {(file.size / 1024).toFixed(1)} KB
                        </td>
                        <td className="px-4 py-2 text-right">
                          <button
                            onClick={() => onPlayAudio(file.name)}
                            className="text-[var(--color-accent)] hover:underline mr-3"
                          >
                            {playingAudio === file.name ? '停止' : '播放'}
                          </button>
                          <button
                            onClick={() => onDeleteAudio(file.name)}
                            className="text-red-500 hover:underline"
                          >
                            删除
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {playingAudio && (
              <audio
                src={audioFileUrl(playingAudio)}
                autoPlay
                onEnded={() => onPlayingAudioChange(null)}
                className="hidden"
              />
            )}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">音频工作站状态</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            音频工作站服务连接状态（端口 8200）
          </p>
          <div className="flex items-center gap-3 p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
            <span
              className={`w-3 h-3 rounded-full ${
                voiceWorkstationStatus === 'connected'
                  ? 'bg-green-500'
                  : voiceWorkstationStatus === 'checking'
                    ? 'bg-yellow-500 animate-pulse'
                    : 'bg-red-500'
              }`}
            />
            <div>
              <div className="text-sm font-medium">音频工作站服务</div>
              <div className="text-xs text-[var(--color-text-tertiary)]">
                {voiceWorkstationStatus === 'connected'
                  ? '已连接'
                  : voiceWorkstationStatus === 'checking'
                    ? '检测中...'
                    : '未连接'}
              </div>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">TTS 基础配置</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            配置 TTS 语音合成的参考音频和文本，用于克隆声音
          </p>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">参考音频</label>
                <select
                  value={audioConfig.ref_audio_path}
                  onChange={(e) =>
                    onAudioConfigChange({ ...audioConfig, ref_audio_path: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                >
                  <option value="">选择音频文件</option>
                  {audioFiles.map((file) => (
                    <option key={file.name} value={file.name}>
                      {file.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">参考文本</label>
                <input
                  type="text"
                  value={audioConfig.ref_text}
                  onChange={(e) =>
                    onAudioConfigChange({ ...audioConfig, ref_text: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="参考音频对应的文本内容"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">
                  语速: {audioConfig.speed}
                </label>
                <input
                  type="range"
                  min="0.5"
                  max={speedMax}
                  value={audioConfig.speed}
                  onChange={(e) =>
                    onAudioConfigChange({ ...audioConfig, speed: parseFloat(e.target.value) })
                  }
                  className="w-full"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">
                  淡入淡出: {audioConfig.cross_fade_duration}s
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={audioConfig.cross_fade_duration}
                  onChange={(e) =>
                    onAudioConfigChange({
                      ...audioConfig,
                      cross_fade_duration: parseFloat(e.target.value),
                    })
                  }
                  className="w-full"
                />
              </div>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">功能开关</h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <label className="text-sm font-medium">情感解析</label>
                <p className="text-xs text-[var(--color-text-tertiary)]">
                  解析文本中的情感标签，使用不同的情感语音
                </p>
              </div>
              <button
                onClick={() =>
                  onAudioConfigChange({
                    ...audioConfig,
                    emotion_enabled: !audioConfig.emotion_enabled,
                  })
                }
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  audioConfig.emotion_enabled
                    ? 'bg-[var(--color-accent)]'
                    : 'bg-[var(--color-border)]'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    audioConfig.emotion_enabled ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <label className="text-sm font-medium">音效</label>
                <p className="text-xs text-[var(--color-text-tertiary)]">
                  解析文本中的音效标签，播放背景音效
                </p>
              </div>
              <button
                onClick={() =>
                  onAudioConfigChange({
                    ...audioConfig,
                    effects_enabled: !audioConfig.effects_enabled,
                  })
                }
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  audioConfig.effects_enabled
                    ? 'bg-[var(--color-accent)]'
                    : 'bg-[var(--color-border)]'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    audioConfig.effects_enabled ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">情感语音配置</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            为不同情感配置专用的参考音频，留空则使用默认配置
          </p>
          <div className="space-y-4">
            {Object.entries(audioConfig.emotion_voices).map(([emotion, config]) => (
              <div
                key={emotion}
                className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]"
              >
                <h4 className="text-sm font-medium mb-3 capitalize">
                  {emotion === 'normal' && '😐 普通'}
                  {emotion === 'happy' && '😊 开心'}
                  {emotion === 'sad' && '😢 悲伤'}
                  {emotion === 'angry' && '😠 愤怒'}
                  {emotion === 'surprised' && '😲 惊讶'}
                  {emotion === 'tender' && '🥰 温柔'}
                </h4>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-[var(--color-text-tertiary)] mb-1 block">
                      参考音频
                    </label>
                    <select
                      value={config.ref_audio}
                      onChange={(e) =>
                        onAudioConfigChange({
                          ...audioConfig,
                          emotion_voices: {
                            ...audioConfig.emotion_voices,
                            [emotion]: { ...config, ref_audio: e.target.value },
                          },
                        })
                      }
                      className="w-full px-2 py-1.5 text-sm bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                    >
                      <option value="">使用默认</option>
                      {audioFiles.map((file) => (
                        <option key={file.name} value={file.name}>
                          {file.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-[var(--color-text-tertiary)] mb-1 block">
                      参考文本
                    </label>
                    <input
                      type="text"
                      value={config.ref_text}
                      onChange={(e) =>
                        onAudioConfigChange({
                          ...audioConfig,
                          emotion_voices: {
                            ...audioConfig.emotion_voices,
                            [emotion]: { ...config, ref_text: e.target.value },
                          },
                        })
                      }
                      className="w-full px-2 py-1.5 text-sm bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                      placeholder="参考文本"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">VAD 语音检测配置</h3>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">VAD 模式</label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={vadConfig.vad.mode === 'energy'}
                    onChange={() =>
                      onVadConfigChange({
                        ...vadConfig,
                        vad: { ...vadConfig.vad, mode: 'energy' },
                      })
                    }
                  />
                  <span className="text-sm">Energy (能量检测)</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={vadConfig.vad.mode === 'webrtc'}
                    onChange={() =>
                      onVadConfigChange({
                        ...vadConfig,
                        vad: { ...vadConfig.vad, mode: 'webrtc' },
                      })
                    }
                  />
                  <span className="text-sm">WebRTC (推荐)</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={vadConfig.vad.mode === 'silero'}
                    onChange={() =>
                      onVadConfigChange({
                        ...vadConfig,
                        vad: { ...vadConfig.vad, mode: 'silero' },
                      })
                    }
                  />
                  <span className="text-sm">Silero (深度学习)</span>
                </label>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">采样率 (Hz)</label>
                <input
                  type="number"
                  value={vadConfig.vad.sample_rate}
                  onChange={(e) =>
                    onVadConfigChange({
                      ...vadConfig,
                      vad: { ...vadConfig.vad, sample_rate: parseInt(e.target.value) || 16000 },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">帧时长 (ms)</label>
                <input
                  type="number"
                  value={vadConfig.vad.frame_duration_ms}
                  onChange={(e) =>
                    onVadConfigChange({
                      ...vadConfig,
                      vad: { ...vadConfig.vad, frame_duration_ms: parseInt(e.target.value) || 30 },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                />
              </div>
            </div>

            {vadConfig.vad.mode === 'energy' && (
              <div>
                <label className="text-sm font-medium mb-2 block">
                  能量阈值: {vadConfig.vad.energy_threshold}
                </label>
                <input
                  type="range"
                  min="100"
                  max="2000"
                  value={vadConfig.vad.energy_threshold}
                  onChange={(e) =>
                    onVadConfigChange({
                      ...vadConfig,
                      vad: { ...vadConfig.vad, energy_threshold: parseInt(e.target.value) },
                    })
                  }
                  className="w-full"
                />
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">静音阈值 (ms)</label>
                <input
                  type="number"
                  value={vadConfig.vad.silence_threshold_ms}
                  onChange={(e) =>
                    onVadConfigChange({
                      ...vadConfig,
                      vad: { ...vadConfig.vad, silence_threshold_ms: parseInt(e.target.value) || 500 },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">语音阈值 (ms)</label>
                <input
                  type="number"
                  value={vadConfig.vad.speech_threshold_ms}
                  onChange={(e) =>
                    onVadConfigChange({
                      ...vadConfig,
                      vad: { ...vadConfig.vad, speech_threshold_ms: parseInt(e.target.value) || 300 },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                />
              </div>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">SenseVoice 流式模式</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            配置 SenseVoice 流式 ASR 参数
          </p>
          <div className="space-y-4 pl-4 border-l-2 border-[var(--color-border)]">
            <div>
              <label className="text-sm font-medium mb-2 block">
                chunk_size: {sensevoiceStreamingConfig.chunk_size}
              </label>
              <input
                type="range"
                min="1000"
                max="3200"
                step="100"
                value={sensevoiceStreamingConfig.chunk_size}
                onChange={(e) =>
                  onSensevoiceStreamingConfigChange({
                    ...sensevoiceStreamingConfig,
                    chunk_size: parseInt(e.target.value),
                  })
                }
                className="w-full"
              />
              <div className="flex justify-between text-xs text-[var(--color-text-tertiary)] mt-1">
                <span>1000 (更快)</span>
                <span>3200 (更稳)</span>
              </div>
            </div>

            <div>
              <label className="text-sm font-medium mb-2 block">
                hop_size: {sensevoiceStreamingConfig.hop_size}
              </label>
              <input
                type="range"
                min="200"
                max="1600"
                step="100"
                value={sensevoiceStreamingConfig.hop_size}
                onChange={(e) =>
                  onSensevoiceStreamingConfigChange({
                    ...sensevoiceStreamingConfig,
                    hop_size: parseInt(e.target.value),
                  })
                }
                className="w-full"
              />
              <div className="flex justify-between text-xs text-[var(--color-text-tertiary)] mt-1">
                <span>200 (低延迟)</span>
                <span>1600 (高延迟)</span>
              </div>
            </div>

            <div>
              <label className="text-sm font-medium mb-2 block">
                look_back: {sensevoiceStreamingConfig.look_back}
              </label>
              <input
                type="range"
                min="2000"
                max="16000"
                step="1000"
                value={sensevoiceStreamingConfig.look_back}
                onChange={(e) =>
                  onSensevoiceStreamingConfigChange({
                    ...sensevoiceStreamingConfig,
                    look_back: parseInt(e.target.value),
                  })
                }
                className="w-full"
              />
              <div className="flex justify-between text-xs text-[var(--color-text-tertiary)] mt-1">
                <span>2000 (短)</span>
                <span>16000 (长)</span>
              </div>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">LLM 轮询配置</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            配置 LLM 流式响应的自适应轮询参数
          </p>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">
                偏移量 (offset_ms): {adaptivePollingConfig.offset_ms}ms
              </label>
              <input
                type="range"
                min="-500"
                max="500"
                step="10"
                value={adaptivePollingConfig.offset_ms}
                onChange={(e) =>
                  onAdaptivePollingConfigChange({
                    ...adaptivePollingConfig,
                    offset_ms: parseInt(e.target.value),
                  })
                }
                className="w-full"
              />
              <div className="flex justify-between text-xs text-[var(--color-text-tertiary)] mt-1">
                <span>-500ms (更快)</span>
                <span>0ms (默认)</span>
                <span>+500ms (更稳)</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">
                  窗口大小: {adaptivePollingConfig.window_size}
                </label>
                <input
                  type="range"
                  min="1"
                  max="10"
                  step="1"
                  value={adaptivePollingConfig.window_size}
                  onChange={(e) =>
                    onAdaptivePollingConfigChange({
                      ...adaptivePollingConfig,
                      window_size: parseInt(e.target.value),
                    })
                  }
                  className="w-full"
                />
                <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                  最近 {adaptivePollingConfig.window_size} 个包取平均
                </p>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">
                  当前间隔 (ms)
                </label>
                <div className="px-3 py-2 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] text-sm">
                  {adaptivePollingStats.current_interval_ms}
                </div>
              </div>
            </div>

            <div className="p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
              <div className="text-xs text-[var(--color-text-tertiary)] mb-2">实时统计</div>
              <div className="grid grid-cols-3 gap-2 text-sm">
                <div>
                  <span className="text-[var(--color-text-tertiary)]">平均延迟:</span>
                  <span className="ml-1 font-medium">{adaptivePollingStats.average_latency_ms.toFixed(1)}ms</span>
                </div>
                <div>
                  <span className="text-[var(--color-text-tertiary)]">采样数:</span>
                  <span className="ml-1 font-medium">{adaptivePollingStats.latency_count}</span>
                </div>
                <div>
                  <span className="text-[var(--color-text-tertiary)]">最近延迟:</span>
                  <span className="ml-1 font-medium">
                    {adaptivePollingStats.recent_latencies.length > 0
                      ? adaptivePollingStats.recent_latencies.slice(-3).map(l => l.toFixed(0)).join(', ') + 'ms'
                      : 'N/A'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">Agent 打断用户</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            配置 Agent 在用户说话时插话的行为
          </p>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <label className="text-sm font-medium">启用 Agent 打断</label>
                <p className="text-xs text-[var(--color-text-tertiary)]">Agent 可以在用户说话时插话</p>
              </div>
              <button
                onClick={() =>
                  onVadConfigChange({
                    ...vadConfig,
                    agent_interrupt: { ...vadConfig.agent_interrupt, enabled: !vadConfig.agent_interrupt.enabled },
                  })
                }
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  vadConfig.agent_interrupt.enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                }`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${vadConfig.agent_interrupt.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>

            {vadConfig.agent_interrupt.enabled && (
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="text-sm font-medium mb-2 block">打断阈值 (ms)</label>
                  <input
                    type="number"
                    value={vadConfig.agent_interrupt.interrupt_threshold_ms}
                    onChange={(e) =>
                      onVadConfigChange({
                        ...vadConfig,
                        agent_interrupt: { ...vadConfig.agent_interrupt, interrupt_threshold_ms: parseInt(e.target.value) || 500 },
                      })
                    }
                    className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium mb-2 block">最小语音时长 (ms)</label>
                  <input
                    type="number"
                    value={vadConfig.agent_interrupt.min_speech_duration_ms}
                    onChange={(e) =>
                      onVadConfigChange({
                        ...vadConfig,
                        agent_interrupt: { ...vadConfig.agent_interrupt, min_speech_duration_ms: parseInt(e.target.value) || 1000 },
                      })
                    }
                    className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium mb-2 block">打断冷却 (ms)</label>
                  <input
                    type="number"
                    value={vadConfig.agent_interrupt.interrupt_cooldown_ms}
                    onChange={(e) =>
                      onVadConfigChange({
                        ...vadConfig,
                        agent_interrupt: { ...vadConfig.agent_interrupt, interrupt_cooldown_ms: parseInt(e.target.value) || 3000 },
                      })
                    }
                    className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  />
                </div>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">用户打断 Agent</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            配置用户打断 Agent TTS 播报的行为
          </p>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <label className="text-sm font-medium">启用打断</label>
                <p className="text-xs text-[var(--color-text-tertiary)]">用户说话时打断当前 TTS 回复</p>
              </div>
              <button
                onClick={() =>
                  onFirewallV3ConfigChange({
                    ...firewallV3Config,
                    interrupt: { ...firewallV3Config.interrupt, enabled: !firewallV3Config.interrupt.enabled },
                  })
                }
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  firewallV3Config.interrupt.enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                }`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${firewallV3Config.interrupt.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>

            {firewallV3Config.interrupt.enabled && (
              <>
                <div>
                  <label className="text-sm font-medium mb-2 block">打断模式</label>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-2">
                      <input
                        type="radio"
                        checked={firewallV3Config.interrupt.mode === 'main_llm'}
                        onChange={() =>
                          onFirewallV3ConfigChange({
                            ...firewallV3Config,
                            interrupt: {
                              ...firewallV3Config.interrupt,
                              mode: 'main_llm',
                              main_llm: { ...firewallV3Config.interrupt.main_llm, enabled: true },
                              independent_llm: { ...firewallV3Config.interrupt.independent_llm, enabled: false },
                            },
                          })
                        }
                      />
                      <span className="text-sm">主 LLM 模式</span>
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="radio"
                        checked={firewallV3Config.interrupt.mode === 'independent_llm'}
                        onChange={() =>
                          onFirewallV3ConfigChange({
                            ...firewallV3Config,
                            interrupt: {
                              ...firewallV3Config.interrupt,
                              mode: 'independent_llm',
                              main_llm: { ...firewallV3Config.interrupt.main_llm, enabled: false },
                              independent_llm: { ...firewallV3Config.interrupt.independent_llm, enabled: true },
                            },
                          })
                        }
                      />
                      <span className="text-sm">独立 LLM 模式</span>
                    </label>
                  </div>
                </div>

                {firewallV3Config.interrupt.mode === 'independent_llm' && (
                  <div>
                    <label className="text-sm font-medium mb-2 block">独立 LLM 模型</label>
                    <input
                      type="text"
                      value={firewallV3Config.interrupt.independent_llm.model}
                      onChange={(e) =>
                        onFirewallV3ConfigChange({
                          ...firewallV3Config,
                          interrupt: {
                            ...firewallV3Config.interrupt,
                            independent_llm: { ...firewallV3Config.interrupt.independent_llm, model: e.target.value },
                          },
                        })
                      }
                      className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                      placeholder="qwen2.5:1.5b"
                    />
                  </div>
                )}
              </>
            )}
          </div>
        </CardBody>
      </Card>

      <div className="flex justify-end mt-6">
        <Button onClick={onSave} loading={saveStatus === 'saving'}>
          {saveStatus === 'saved' ? '已保存' : '保存配置'}
        </Button>
      </div>
    </div>
  );
}
