export type ActiveSection = 'appearance' | 'service' | 'audio' | 'live' | 'live2d' | 'vector' | 'graph' | 'llm' | 'plugin';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export interface BackendStatus {
  pid?: number;
  uptime?: number;
  port?: number;
}

export interface GatewayServicesConfig {
  monolith: { url: string; http_url: string; timeout: number; status: string };
}

export interface VectorConfig {
  backend: string;
  vectorSize: number;
  dbPath: string;
  collectionName: string;
  weaviateHost: string;
  weaviatePort: number;
  qdrantHost: string;
  qdrantPort: number;
  embeddingProvider: string;
  embeddingModel: string;
  embeddingApiBase: string;
  embeddingApiKey: string;
}

export interface ModelEntry {
  provider: string;
  host: string;
  model: string;
  apiKey: string;
  enabled: boolean;
}

export interface ModelsConfig {
  main: ModelEntry;
  summary: ModelEntry;
  memory: ModelEntry;
}

export interface LlmParams {
  temperature: number;
  maxTokens: number;
  topP: number;
  timeout: number;
}

export interface EmotionVoice {
  ref_audio: string;
  ref_text: string;
}

export interface AudioConfig {
  ref_audio_path: string;
  ref_text: string;
  speed: number;
  cross_fade_duration: number;
  emotion_enabled: boolean;
  effects_enabled: boolean;
  emotion_voices: Record<string, EmotionVoice>;
}

export interface AudioFile {
  name: string;
  size: number;
  modified: number;
}

export interface DanmakuConfig {
  websocket: { endpoint: string; max_connections: number };
  sources: {
    bilibili: { enabled: boolean; websocket_url: string };
    rdf: { enabled: boolean; websocket_url: string };
  };
}

export interface FirewallConfig {
  llm: { default_model: string };
  blocking: { blacklist_enabled: boolean; blacklist: string[] };
  decision: { timeout_ms: number };
}

export interface FirewallV3Config {
  interrupt: {
    enabled: boolean;
    mode: 'main_llm' | 'independent_llm';
    main_llm: { enabled: boolean; prompt: string };
    independent_llm: { enabled: boolean; model: string };
  };
}

export interface VadConfig {
  vad: {
    mode: 'energy' | 'webrtc' | 'silero';
    sample_rate: number;
    frame_duration_ms: number;
    energy_threshold: number;
    silence_threshold_ms: number;
    speech_threshold_ms: number;
  };
  audio_stream: {
    asr_interval_ms: number;
    buffer_duration_ms: number;
  };
  agent_interrupt: {
    enabled: boolean;
    interrupt_threshold_ms: number;
    min_speech_duration_ms: number;
    interrupt_cooldown_ms: number;
  };
}

export interface SensevoiceStreamingConfig {
  chunk_size: number;
  hop_size: number;
  look_back: number;
}

export interface AdaptivePollingConfig {
  offset_ms: number;
  window_size: number;
}

export interface AdaptivePollingStats {
  current_interval_ms: number;
  average_latency_ms: number;
  latency_count: number;
  recent_latencies: number[];
}

export interface GraphConfig {
  graph_enabled: boolean;
  graph_backend: string;
  graph_libraries: Record<string, { enabled: boolean; label_prefix: string }>;
}

export interface GraphHealth {
  status: string;
  graph_enabled: boolean;
  connected: boolean;
  message: string;
}

export interface GraphStats {
  graph_enabled: boolean;
  connected: boolean;
  libraries: Record<string, { entity_count: number; relation_count: number }>;
  database_path?: string;
}

export interface LiveClientStatus {
  connected: boolean;
  client_id?: string;
  room_id?: string;
  client_type?: string;
}

export type VoiceWorkstationStatus = 'connected' | 'disconnected' | 'checking';

export interface SettingSection {
  id: string;
  title: string;
  icon: React.ReactNode;
  description: string;
}

export const themeOptions = [
  { value: 'light', label: '浅色', icon: '☀️', description: '明亮清爽的界面' },
  { value: 'dark', label: '深色', icon: '🌙', description: '护眼暗色主题' },
  { value: 'system', label: '跟随系统', icon: '💻', description: '自动跟随系统设置' },
];

export const accentColors = [
  { value: '#3b82f6', label: '蓝色', class: 'bg-blue-500' },
  { value: '#8b5cf6', label: '紫色', class: 'bg-violet-500' },
  { value: '#10b981', label: '绿色', class: 'bg-emerald-500' },
  { value: '#f59e0b', label: '橙色', class: 'bg-amber-500' },
  { value: '#ef4444', label: '红色', class: 'bg-red-500' },
  { value: '#ec4899', label: '粉色', class: 'bg-pink-500' },
];
