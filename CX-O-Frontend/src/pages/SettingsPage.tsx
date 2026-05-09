import { useState, useEffect, useCallback, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { cn } from '../lib/utils';
import { useThemeStore } from '../store/themeStore';
import { useSettingsStore } from '../store/settingsStore';
import { PageHeader } from '../components/layout';
import { Button, Card, CardBody } from '../components/ui';

interface SettingSection {
  id: string;
  title: string;
  icon: React.ReactNode;
  description: string;
}

const sections: SettingSection[] = [
  {
    id: 'appearance',
    title: '外观设置',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01"
        />
      </svg>
    ),
    description: '主题、颜色和界面设置',
  },
  {
    id: 'service',
    title: '服务管理',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"
        />
      </svg>
    ),
    description: '启动/停止后端服务',
  },
  {
    id: 'audio',
    title: '音频设置',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
        />
      </svg>
    ),
    description: 'TTS、VAD 语音检测、双向打断配置',
  },
  {
    id: 'live',
    title: '直播管理',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
        />
      </svg>
    ),
    description: '弹幕接收和直播客户端配置',
  },
  {
    id: 'live2d',
    title: '虚拟形象',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
        />
      </svg>
    ),
    description: 'Live2D 和 VRM 3D 虚拟形象设置',
  },
  {
    id: 'vector',
    title: '向量存储',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
        />
      </svg>
    ),
    description: '配置向量数据库连接',
  },
  {
    id: 'graph',
    title: '图数据库',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
        />
      </svg>
    ),
    description: '配置 Neo4j 图数据库',
  },
  {
    id: 'llm',
    title: '模型设置',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
        />
      </svg>
    ),
    description: '配置大语言模型参数',
  },
];

const themeOptions = [
  { value: 'light', label: '浅色', icon: '☀️', description: '明亮清爽的界面' },
  { value: 'dark', label: '深色', icon: '🌙', description: '护眼暗色主题' },
  { value: 'system', label: '跟随系统', icon: '💻', description: '自动跟随系统设置' },
];

const accentColors = [
  { value: '#3b82f6', label: '蓝色', class: 'bg-blue-500' },
  { value: '#8b5cf6', label: '紫色', class: 'bg-violet-500' },
  { value: '#10b981', label: '绿色', class: 'bg-emerald-500' },
  { value: '#f59e0b', label: '橙色', class: 'bg-amber-500' },
  { value: '#ef4444', label: '红色', class: 'bg-red-500' },
  { value: '#ec4899', label: '粉色', class: 'bg-pink-500' },
];

export function SettingsPage() {
  const [activeSection, setActiveSection] = useState<'appearance' | 'service' | 'audio' | 'live' | 'live2d' | 'vector' | 'graph' | 'llm'>(
    'appearance'
  );
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [logs, setLogs] = useState('');
  const [isBackendRunning, setIsBackendRunning] = useState(false);
  const [isControlServiceReady, setIsControlServiceReady] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  // 虚拟形象设置
  const { live2d: live2dSettings, vrm: vrmSettings, avatarType, setLive2DSettings, setVRMSettings, setAvatarType } = useSettingsStore();
  const [backendStatus, setBackendStatus] = useState<{
    pid?: number;
    uptime?: number;
    port?: number;
  }>({});
  const [themeTransition, setThemeTransition] = useState(false);

  const { theme, setTheme } = useThemeStore();
  const [selectedAccent, setSelectedAccent] = useState('#3b82f6');

  const themeTransitionTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const saveStatusTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    return () => {
      if (themeTransitionTimeoutRef.current) {
        clearTimeout(themeTransitionTimeoutRef.current);
      }
      if (saveStatusTimeoutRef.current) {
        clearTimeout(saveStatusTimeoutRef.current);
      }
    };
  }, []);

  const handleThemeChange = (newTheme: 'light' | 'dark' | 'system') => {
    setThemeTransition(true);
    setTheme(newTheme);
    if (themeTransitionTimeoutRef.current) {
      clearTimeout(themeTransitionTimeoutRef.current);
    }
    themeTransitionTimeoutRef.current = setTimeout(() => setThemeTransition(false), 300);
  };

  const checkControlService = useCallback(async () => {
    try {
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8100';
      const response = await fetch(`${apiUrl}/health`);
      if (response.ok) {
        setIsControlServiceReady(true);
        return true;
      }
      setIsControlServiceReady(false);
      return false;
    } catch {
      setIsControlServiceReady(false);
      return false;
    }
  }, []);

  const checkBackendStatus = useCallback(async () => {
    try {
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8100';
      const response = await fetch(`${apiUrl}/health`);
      if (response.ok) {
        setIsBackendRunning(true);
        const port = new URL(apiUrl).port;
        setBackendStatus({ port: parseInt(port, 10) });
        return true;
      }
      setIsBackendRunning(false);
      setBackendStatus({});
      return false;
    } catch {
      setIsBackendRunning(false);
      setBackendStatus({});
      return false;
    }
  }, []);

  useEffect(() => {
    checkControlService();
    checkBackendStatus();
    const interval = setInterval(() => {
      checkControlService();
      checkBackendStatus();
    }, 3000);
    return () => clearInterval(interval);
  }, [checkControlService, checkBackendStatus]);

  const { data: serviceConfig } = useQuery({
    queryKey: ['serviceConfig'],
    queryFn: () => api.getServiceConfig(),
    enabled: isBackendRunning,
  });

  const [gatewayServicesConfig, setGatewayServicesConfig] = useState({
    monolith: { url: 'ws://127.0.0.1:8100/ws', http_url: 'http://127.0.0.1:8100', timeout: 30, status: '集成' },
  });

  useEffect(() => {
    const loadGatewayConfig = async () => {
      if (!isBackendRunning) return;
      try {
        const data = await api.getServiceConfig() as { status?: string; config?: typeof gatewayServicesConfig };
        if (data.status === 'success' && data.config) {
          setGatewayServicesConfig(data.config);
        }
      } catch (error) {
        console.error('Failed to load Gateway config:', error);
      }
    };
    loadGatewayConfig();
  }, [isBackendRunning]);

  const handleUpdateGatewayServices = async () => {
    try {
      await api.updateServiceConfig(gatewayServicesConfig);
      alert('Gateway 服务配置已保存，需要重启服务生效');
    } catch (error) {
      console.error('Failed to update Gateway config:', error);
      alert('保存失败');
    }
  };

  void handleUpdateGatewayServices;

  const [vectorConfig, setVectorConfig] = useState({
    backend: 'weaviate',
    vectorSize: 768,
    dbPath: 'data/chroma_db',
    collectionName: 'memory_vectors',
    weaviateHost: 'localhost',
    weaviatePort: 8090,
    qdrantHost: 'localhost',
    qdrantPort: 6333,
  });

  const [modelsConfig, setModelsConfig] = useState({
    main: {
      provider: 'ollama',
      host: 'http://localhost:11434',
      model: 'llama3.2:3b',
      apiKey: '',
      enabled: true,
    },
    summary: {
      provider: 'ollama',
      host: 'http://localhost:11434',
      model: 'llama3.2:3b',
      apiKey: '',
      enabled: false,
    },
    memory: {
      provider: 'ollama',
      host: 'http://localhost:11434',
      model: 'llama3.2:3b',
      apiKey: '',
      enabled: false,
    },
  });

  const [llmParams, setLlmParams] = useState({
    temperature: 0.7,
    maxTokens: 0,
    topP: 0.9,
    timeout: 30,
  });

  const [audioConfig, setAudioConfig] = useState({
    ref_audio_path: '',
    ref_text: '',
    speed: 1.0,
    cross_fade_duration: 0.15,
    emotion_enabled: true,
    effects_enabled: true,
    emotion_voices: {
      normal: { ref_audio: '', ref_text: '' },
      happy: { ref_audio: '', ref_text: '' },
      sad: { ref_audio: '', ref_text: '' },
      angry: { ref_audio: '', ref_text: '' },
      surprised: { ref_audio: '', ref_text: '' },
      tender: { ref_audio: '', ref_text: '' },
    } as Record<string, { ref_audio: string; ref_text: string }>,
  });

  const [audioFiles, setAudioFiles] = useState<{ name: string; size: number; modified: number }[]>([]);
  const [uploadingFile, setUploadingFile] = useState(false);
  const [playingAudio, setPlayingAudio] = useState<string | null>(null);
  const [voiceWorkstationStatus, setVoiceWorkstationStatus] = useState<'connected' | 'disconnected' | 'checking'>('checking');

  const [danmakuConfig, setDanmakuConfig] = useState({
    websocket: {
      endpoint: '/ws/live',
      max_connections: 100,
    },
    sources: {
      bilibili: { enabled: true, websocket_url: 'ws://localhost:8080' },
      rdf: { enabled: true, websocket_url: 'ws://localhost:9898' },
    },
  });

  const [firewallConfig, setFirewallConfig] = useState({
    llm: { default_model: 'qwen2.5:latest' },
    blocking: { blacklist_enabled: true, blacklist: [] as string[] },
    decision: { timeout_ms: 5000 },
  });

  const [firewallV3Config, setFirewallV3Config] = useState({
    interrupt: {
      enabled: true,
      mode: 'main_llm' as 'main_llm' | 'independent_llm',
      main_llm: { enabled: true, prompt: '' },
      independent_llm: { enabled: false, model: 'qwen2.5:1.5b' },
    },
  });

  const [vadConfig, setVadConfig] = useState({
    vad: {
      mode: 'webrtc' as 'energy' | 'webrtc' | 'silero',
      sample_rate: 16000,
      frame_duration_ms: 30,
      energy_threshold: 500,
      silence_threshold_ms: 500,
      speech_threshold_ms: 300,
    },
    audio_stream: {
      asr_interval_ms: 500,
      buffer_duration_ms: 1000,
    },
    agent_interrupt: {
      enabled: true,
      interrupt_threshold_ms: 500,
      min_speech_duration_ms: 1000,
      interrupt_cooldown_ms: 3000,
    },
  });

  const [sensevoiceStreamingConfig, setSensevoiceStreamingConfig] = useState({
    chunk_size: 1600,
    hop_size: 800,
    look_back: 8000,
  });

  const [adaptivePollingConfig, setAdaptivePollingConfig] = useState({
    offset_ms: 0,
    window_size: 3,
  });

  const [adaptivePollingStats, setAdaptivePollingStats] = useState({
    current_interval_ms: 100,
    average_latency_ms: 0,
    latency_count: 0,
    recent_latencies: [] as number[],
  });

  const [graphConfig, setGraphConfig] = useState({
    graph_enabled: false,
    graph_backend: 'neo4j',
    neo4j: {
      uri: 'bolt://localhost:7687',
      user: 'neo4j',
      password: 'password',
      database: 'neo4j',
      max_connection_pool_size: 50,
    },
    graph_libraries: {
      user: { enabled: true, label_prefix: 'User' },
      thing: { enabled: true, label_prefix: 'Thing' },
      concept: { enabled: true, label_prefix: 'Concept' },
      event: { enabled: true, label_prefix: 'Event' },
    },
  });

  const [graphHealth, setGraphHealth] = useState<{
    status: string;
    graph_enabled: boolean;
    connected: boolean;
    message: string;
  } | null>(null);

  const [graphStats, setGraphStats] = useState<{
    graph_enabled: boolean;
    connected: boolean;
    libraries: Record<string, { entity_count: number; relation_count: number }>;
  } | null>(null);

  const [liveClientStatus, setLiveClientStatus] = useState<{
    connected: boolean;
    client_id?: string;
    room_id?: string;
    client_type?: string;
  }>({ connected: false });

  const [newBlacklistUid, setNewBlacklistUid] = useState('');

  useEffect(() => {
    const loadAudioConfig = async () => {
      try {
        const data = await api.getAudioConfig() as { config?: {
          ref_audio_path?: string;
          ref_text?: string;
          speed?: number;
          cross_fade_duration?: number;
          emotion_enabled?: boolean;
          effects_enabled?: boolean;
          emotion_voices?: Record<string, { ref_audio: string; ref_text: string }>;
        } };
        if (data.config) {
          setAudioConfig({
            ref_audio_path: data.config.ref_audio_path || '',
            ref_text: data.config.ref_text || '',
            speed: data.config.speed || 1.0,
            cross_fade_duration: data.config.cross_fade_duration || 0.15,
            emotion_enabled: data.config.emotion_enabled ?? true,
            effects_enabled: data.config.effects_enabled ?? true,
            emotion_voices: data.config.emotion_voices || {
              normal: { ref_audio: '', ref_text: '' },
              happy: { ref_audio: '', ref_text: '' },
              sad: { ref_audio: '', ref_text: '' },
              angry: { ref_audio: '', ref_text: '' },
              surprised: { ref_audio: '', ref_text: '' },
              tender: { ref_audio: '', ref_text: '' },
            },
          });
        }
      } catch (error) {
        console.error('Failed to load audio config:', error);
      }
    };
    loadAudioConfig();
  }, []);

  useEffect(() => {
    const loadAudioFiles = async () => {
      try {
        const data = await api.getAudioFiles() as { files?: { name: string; size: number; modified: string }[] };
        if (data.files) {
          setAudioFiles(data.files.map(f => ({ ...f, modified: new Date(f.modified).getTime() })));
        }
      } catch (error) {
        console.error('Failed to load audio files:', error);
      }
    };
    loadAudioFiles();
  }, []);

  useEffect(() => {
    const checkVoiceWorkstation = async () => {
      try {
        await api.getVoiceWorkstationStatus();
        setVoiceWorkstationStatus('connected');
      } catch {
        setVoiceWorkstationStatus('disconnected');
      }
    };
    checkVoiceWorkstation();
    const interval = setInterval(checkVoiceWorkstation, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const loadLiveConfigs = async () => {
      try {
        const [danmakuData, firewallData, firewallV3Data, liveStatus, vadData, sensevoiceData, adaptivePollingData] = await Promise.all([
          api.getDanmakuConfig(),
          api.getFirewallConfig(),
          api.getFirewallV3Config(),
          api.getLiveClientStatus(),
          api.getVadConfig(),
          api.getSenseVoiceStreamingConfig(),
          api.getAdaptivePollingConfig(),
        ]) as [unknown, unknown, unknown, unknown, unknown, unknown, unknown];

        if (danmakuData && typeof danmakuData === 'object' && 'config' in danmakuData) {
          setDanmakuConfig((danmakuData as { config: typeof danmakuConfig }).config);
        }
        if (firewallData && typeof firewallData === 'object' && 'config' in firewallData) {
          setFirewallConfig((firewallData as { config: typeof firewallConfig }).config);
        }
        if (firewallV3Data && typeof firewallV3Data === 'object' && 'config' in firewallV3Data) {
          setFirewallV3Config((firewallV3Data as { config: typeof firewallV3Config }).config);
        }
        if (liveStatus && typeof liveStatus === 'object') {
          setLiveClientStatus(liveStatus as typeof liveClientStatus);
        }
        if (vadData && typeof vadData === 'object' && 'config' in vadData) {
          setVadConfig((vadData as { config: typeof vadConfig }).config);
        }
        if (sensevoiceData && typeof sensevoiceData === 'object' && 'config' in sensevoiceData) {
          const cfg = (sensevoiceData as { config: { chunk_size?: number; hop_size?: number; look_back?: number } }).config;
          setSensevoiceStreamingConfig({
            chunk_size: cfg.chunk_size ?? 1600,
            hop_size: cfg.hop_size ?? 800,
            look_back: cfg.look_back ?? 8000,
          });
        }
        if (adaptivePollingData && typeof adaptivePollingData === 'object') {
          const apData = adaptivePollingData as { config?: { offset_ms?: number; window_size?: number }; stats?: typeof adaptivePollingStats };
          if (apData.config) {
            setAdaptivePollingConfig({
              offset_ms: apData.config.offset_ms ?? 0,
              window_size: apData.config.window_size ?? 3,
            });
          }
          if (apData.stats) {
            setAdaptivePollingStats(apData.stats);
          }
        }
      } catch (error) {
        console.error('Failed to load live configs:', error);
      }
    };
    if (isBackendRunning) {
      loadLiveConfigs();
    }
  }, [isBackendRunning]);

  useEffect(() => {
    const loadGraphConfig = async () => {
      if (!isBackendRunning) return;
      try {
        const [configData, healthData, statsData] = await Promise.all([
          api.getGraphConfig(),
          api.getGraphHealth(),
          api.getGraphStatus(),
        ]) as [unknown, unknown, unknown];

        const cfg = configData as { status?: string; config?: {
          graph_enabled?: boolean;
          graph_backend?: string;
          neo4j?: typeof graphConfig.neo4j;
          graph_libraries?: typeof graphConfig.graph_libraries;
        } };
        if (cfg.status === 'success' && cfg.config) {
          setGraphConfig({
            graph_enabled: cfg.config.graph_enabled ?? false,
            graph_backend: cfg.config.graph_backend ?? 'neo4j',
            neo4j: cfg.config.neo4j ?? graphConfig.neo4j,
            graph_libraries: cfg.config.graph_libraries ?? graphConfig.graph_libraries,
          });
        }
        if (healthData && typeof healthData === 'object') {
          setGraphHealth(healthData as typeof graphHealth);
        }
        const st = statsData as { status?: string; graph_status?: typeof graphStats };
        if (st.status === 'success' && st.graph_status) {
          setGraphStats(st.graph_status);
        }
      } catch (error) {
        console.error('Failed to load graph config:', error);
      }
    };
    loadGraphConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isBackendRunning]);

  const handleAudioUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploadingFile(true);
    try {
      const result = await api.uploadAudioFile(file);
      if (result.filename) {
        setAudioFiles((prev) => [
          ...prev,
          { name: result.filename, size: file.size, modified: Date.now() },
        ]);
      }
    } catch (error) {
      console.error('Upload error:', error);
      alert('上传失败');
    } finally {
      setUploadingFile(false);
      e.target.value = '';
    }
  };

  const handlePlayAudio = (filename: string) => {
    if (playingAudio === filename) {
      setPlayingAudio(null);
    } else {
      setPlayingAudio(filename);
    }
  };

  const handleDeleteAudio = async (filename: string) => {
    if (!confirm(`确定要删除 ${filename} 吗？`)) return;

    try {
      await api.deleteAudioFile(filename);
      setAudioFiles((prev) => prev.filter((f) => f.name !== filename));
    } catch (error) {
      console.error('Delete error:', error);
      alert('删除失败');
    }
  };

  useEffect(() => {
    if (serviceConfig && typeof serviceConfig === 'object' && 'config' in serviceConfig) {
      const cfg = (serviceConfig as { config: Record<string, unknown> }).config;
      if (cfg.vector && typeof cfg.vector === 'object') {
        const vec = cfg.vector as Record<string, unknown>;
        setVectorConfig({
          backend: (vec.backend as string) ?? (vec.vector_backend as string) ?? 'weaviate',
          vectorSize: (vec.vector_size as number) ?? 768,
          dbPath: (vec.db_path as string) ?? 'data/chroma_db',
          collectionName: (vec.collection_name as string) ?? 'memory_vectors',
          weaviateHost: (vec.host as string) ?? (vec.weaviate_host as string) ?? 'localhost',
          weaviatePort: (vec.port as number) ?? (vec.weaviate_port as number) ?? 8090,
          qdrantHost: (vec.qdrant_host as string) ?? 'localhost',
          qdrantPort: (vec.qdrant_port as number) ?? 6333,
        });
      }
      if (cfg.models && typeof cfg.models === 'object') {
        const models = cfg.models as Record<string, unknown>;
        setModelsConfig((prev) => ({
          main: models.main ? { ...prev.main, ...(models.main as Record<string, unknown>) } : prev.main,
          summary: models.summary ? { ...prev.summary, ...(models.summary as Record<string, unknown>) } : prev.summary,
          memory: models.memory ? { ...prev.memory, ...(models.memory as Record<string, unknown>) } : prev.memory,
        }));
      }
      if (cfg.llm_params && typeof cfg.llm_params === 'object') {
        const llm = cfg.llm_params as Record<string, unknown>;
        setLlmParams({
          temperature: (llm.temperature as number) ?? 0.7,
          maxTokens: (llm.maxTokens as number) ?? 2048,
          topP: (llm.topP as number) ?? 0.9,
          timeout: (llm.timeout as number) ?? 30,
        });
      }
    }
  }, [serviceConfig]);

  const loadLogs = useCallback(async () => {
    if (!isBackendRunning) {
      setLogs('后端服务未运行，启动服务后查看日志');
      return;
    }
    if (!isControlServiceReady) {
      setLogs('控制服务未就绪，请稍等...');
      return;
    }
    try {
      const data = await api.getServiceLogs(50);
      setLogs(data.logs || '暂无日志');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : '未知错误';
      setLogs(`加载日志失败: ${errorMessage}\n请检查后端服务是否正常运行`);
    }
  }, [isBackendRunning, isControlServiceReady]);

  useEffect(() => {
    if (activeSection === 'service') {
      loadLogs();
      const interval = setInterval(loadLogs, 3000);
      return () => clearInterval(interval);
    }
  }, [activeSection, loadLogs]);

  const handleStartBackend = async () => {
    setIsProcessing(true);
    try {
      const response = await fetch('http://localhost:8100/health');
      if (response.ok) {
        alert('后端服务已在运行');
        setIsBackendRunning(true);
      } else {
        alert('请手动启动后端服务: cd backend && python main.py');
      }
    } catch {
      alert('请手动启动后端服务: cd backend && python main.py');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleStopBackend = async () => {
    alert('请手动停止后端服务 (Ctrl+C)');
  };

  const handleRestartBackend = async () => {
    alert('请手动重启后端服务');
  };

  const handleSave = async () => {
    setSaveStatus('saving');
    try {
      switch (activeSection) {
        case 'audio':
          await api.updateConfig('audio', audioConfig);
          break;
        case 'live':
          await api.updateConfig('live', {
            danmaku: danmakuConfig,
            firewall: firewallConfig,
            firewall_v3: firewallV3Config,
            vad: vadConfig,
            sensevoice_streaming: sensevoiceStreamingConfig,
            adaptive_polling: adaptivePollingConfig,
          });
          break;
        case 'vector':
          await api.updateConfig('vector', vectorConfig);
          break;
        case 'graph':
          await api.updateConfig('graph', graphConfig);
          break;
        case 'llm': {
          const updatedModelDefaults = {
            summary: modelsConfig.summary.enabled ? 'summary' : 'main',
            memory: modelsConfig.memory.enabled ? 'memory' : 'main',
          };
          await api.updateConfig('llm', {
            models: modelsConfig,
            model_defaults: updatedModelDefaults,
            llm_params: llmParams,
          });
          localStorage.setItem('cxhms-current-model', modelsConfig.main.model);
          break;
        }
      }
      setSaveStatus('saved');
    } catch {
      setSaveStatus('error');
    }
    if (saveStatusTimeoutRef.current) {
      clearTimeout(saveStatusTimeoutRef.current);
    }
    saveStatusTimeoutRef.current = setTimeout(() => setSaveStatus('idle'), 2000);
  };

  return (
    <div className={`max-w-6xl mx-auto ${themeTransition ? 'transition-colors duration-300' : ''}`}>
      <PageHeader title="系统设置" description="配置系统外观、服务和行为" />

      <div className="flex gap-6">
        <nav className="w-56 flex-shrink-0 space-y-1">
          {sections.map((section) => (
            <button
              key={section.id}
              onClick={() => setActiveSection(section.id as typeof activeSection)}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-lg)] text-sm font-medium transition-colors text-left',
                activeSection === section.id
                  ? 'bg-[var(--color-accent-light)] text-[var(--color-accent)]'
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]'
              )}
            >
              {section.icon}
              <div>
                <div>{section.title}</div>
                <div className="text-xs text-[var(--color-text-tertiary)] font-normal">
                  {section.description}
                </div>
              </div>
            </button>
          ))}
        </nav>

        <div className="flex-1 min-w-0">
          {activeSection === 'appearance' && (
            <div className="space-y-6">
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">主题设置</h3>
                  <div className="grid grid-cols-3 gap-4">
                    {themeOptions.map((option) => (
                      <button
                        key={option.value}
                        onClick={() => handleThemeChange(option.value as typeof theme)}
                        className={cn(
                          'p-4 rounded-[var(--radius-lg)] border-2 transition-all text-left',
                          theme === option.value
                            ? 'border-[var(--color-accent)] bg-[var(--color-accent-light)]'
                            : 'border-[var(--color-border)] hover:border-[var(--color-accent)]/50'
                        )}
                      >
                        <div className="text-2xl mb-2">{option.icon}</div>
                        <div className="font-medium">{option.label}</div>
                        <div className="text-xs text-[var(--color-text-tertiary)]">
                          {option.description}
                        </div>
                      </button>
                    ))}
                  </div>
                </CardBody>
              </Card>

              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">强调色</h3>
                  <div className="flex gap-3">
                    {accentColors.map((color) => (
                      <button
                        key={color.value}
                        onClick={() => setSelectedAccent(color.value)}
                        className={cn(
                          'w-10 h-10 rounded-full transition-all',
                          color.class,
                          selectedAccent === color.value
                            ? 'ring-2 ring-offset-2 ring-[var(--color-accent)] scale-110'
                            : 'hover:scale-105'
                        )}
                        title={color.label}
                      />
                    ))}
                  </div>
                  <p className="text-xs text-[var(--color-text-tertiary)] mt-3">
                    强调色用于按钮、链接和高亮元素
                  </p>
                </CardBody>
              </Card>

              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">连接设置</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium mb-2">离线超时时间</label>
                      <p className="text-xs text-[var(--color-text-tertiary)] mb-3">
                        当前端断开连接超过此时间后，系统将自动保存当前上下文到长期记忆
                      </p>
                      <select
                        value={localStorage.getItem('cxhms-offline-timeout') || '60'}
                        onChange={(e) => {
                          localStorage.setItem('cxhms-offline-timeout', e.target.value);
                          window.dispatchEvent(
                            new CustomEvent('offline-timeout-change', { detail: e.target.value })
                          );
                        }}
                        className="w-full px-3 py-2 bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] rounded-[var(--radius-md)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
                      >
                        <option value="30">30 秒</option>
                        <option value="60">60 秒（默认）</option>
                        <option value="120">2 分钟</option>
                        <option value="300">5 分钟</option>
                      </select>
                    </div>
                  </div>
                </CardBody>
              </Card>

              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">界面预览</h3>
                  <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-10 h-10 rounded-full bg-[var(--color-accent)] flex items-center justify-center text-[var(--color-bg-primary)]">
                        AI
                      </div>
                      <div>
                        <div className="font-medium">示例标题</div>
                        <div className="text-sm text-[var(--color-text-secondary)]">
                          这是一个预览文本
                        </div>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm">主要按钮</Button>
                      <Button variant="secondary" size="sm">
                        次要按钮
                      </Button>
                      <Button variant="ghost" size="sm">
                        幽灵按钮
                      </Button>
                    </div>
                  </div>
                </CardBody>
              </Card>
            </div>
          )}

          {activeSection === 'service' && (
            <div className="space-y-6">
              <Card>
                <CardBody>
                  <div className="flex items-center justify-between mb-6">
                    <div>
                      <h3 className="text-lg font-semibold">服务状态</h3>
                      <p className="text-sm text-[var(--color-text-secondary)]">
                        单体架构服务 - ASR/TTS 已集成
                      </p>
                    </div>
                  </div>

                  <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)] mb-4">
                    <div className="flex items-center gap-3 mb-3">
                      <div className={`w-3 h-3 rounded-full ${isBackendRunning ? 'bg-green-500' : 'bg-gray-400'}`} />
                      <span className="font-medium">
                        {isBackendRunning ? '单体服务运行中' : '服务未运行'}
                      </span>
                    </div>
                    <div className="text-sm text-[var(--color-text-secondary)]">
                      <p>WebSocket: <code className="px-1 py-0.5 bg-[var(--color-bg-primary)] rounded">ws://127.0.0.1:8100/ws</code></p>
                      <p>HTTP API: <code className="px-1 py-0.5 bg-[var(--color-bg-primary)] rounded">http://127.0.0.1:8100</code></p>
                    </div>
                  </div>

                  <div className="p-3 bg-blue-500/10 border border-blue-500/30 rounded-[var(--radius-md)] text-sm text-blue-600 dark:text-blue-400">
                    <p className="font-medium mb-1">架构变更说明</p>
                    <p>系统已从微服务架构重构为单体架构。ASR（语音识别）和 TTS（语音合成）功能已直接集成到主服务中，无需单独配置微服务端点。</p>
                  </div>
                </CardBody>
              </Card>

              <Card>
                <CardBody>
                  <div className="flex items-center justify-between mb-6">
                    <div>
                      <h3 className="text-lg font-semibold">服务管理</h3>
                      <p className="text-sm text-[var(--color-text-secondary)]">
                        启动/停止单体服务
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {isBackendRunning ? (
                        <>
                          <Button
                            variant="secondary"
                            onClick={handleRestartBackend}
                            loading={isProcessing}
                          >
                            重启
                          </Button>
                          <Button
                            variant="danger"
                            onClick={handleStopBackend}
                            loading={isProcessing}
                          >
                            停止
                          </Button>
                        </>
                      ) : (
                        <Button
                          onClick={handleStartBackend}
                          loading={isProcessing}
                        >
                          启动服务
                        </Button>
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-4 p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
                    <div>
                      <span className="text-xs text-[var(--color-text-tertiary)]">状态</span>
                      <p className="font-medium flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${isBackendRunning ? 'bg-green-500' : 'bg-red-500'}`}
                        />
                        {isBackendRunning ? '运行中' : '已停止'}
                      </p>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--color-text-tertiary)]">端口</span>
                      <p className="font-medium">8100</p>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--color-text-tertiary)]">进程 ID</span>
                      <p className="font-medium">{backendStatus.pid || '-'}</p>
                    </div>
                  </div>
                </CardBody>
              </Card>

              <Card>
                <CardBody>
                  <h4 className="font-semibold mb-4">服务日志</h4>
                  <div className="bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)] p-4 font-mono text-sm text-[var(--color-success)] h-64 overflow-auto whitespace-pre-wrap">
                    {logs}
                  </div>
                </CardBody>
              </Card>
            </div>
          )}

          {activeSection === 'vector' && (
            <div className="space-y-6">
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">向量存储配置</h3>
                  <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                    向量存储用于语义搜索和记忆检索
                  </p>
                  <div className="space-y-4">
                    <div>
                      <label className="text-sm font-medium mb-2 block">向量存储后端</label>
                      <select
                        value={vectorConfig.backend}
                        onChange={(e) =>
                          setVectorConfig({ ...vectorConfig, backend: e.target.value })
                        }
                        className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                      >
                        <option value="weaviate">Weaviate (独立服务)</option>
                        <option value="weaviate_embedded">Weaviate Embedded (内置)</option>
                      </select>
                      <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                        仅支持 Weaviate。Chroma、Milvus Lite、Qdrant 已不再支持。
                      </p>
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-2 block">向量维度</label>
                      <select
                        value={vectorConfig.vectorSize}
                        onChange={(e) =>
                          setVectorConfig({ ...vectorConfig, vectorSize: parseInt(e.target.value) })
                        }
                        className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                      >
                        <option value={384}>384 (小型模型)</option>
                        <option value={768}>768 (中型模型)</option>
                        <option value={1024}>1024 (大型模型)</option>
                        <option value={1536}>1536 (OpenAI)</option>
                      </select>
                    </div>
                    {vectorConfig.backend === 'weaviate' && (
                      <>
                        <div>
                          <label className="text-sm font-medium mb-2 block">Weaviate 主机</label>
                          <input
                            type="text"
                            value={vectorConfig.weaviateHost}
                            onChange={(e) =>
                              setVectorConfig({ ...vectorConfig, weaviateHost: e.target.value })
                            }
                            className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                            placeholder="localhost"
                          />
                        </div>
                        <div>
                          <label className="text-sm font-medium mb-2 block">Weaviate 端口</label>
                          <input
                            type="number"
                            value={vectorConfig.weaviatePort}
                            onChange={(e) =>
                              setVectorConfig({
                                ...vectorConfig,
                                weaviatePort: parseInt(e.target.value),
                              })
                            }
                            className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                            placeholder="8090"
                          />
                        </div>
                      </>
                    )}
                    {vectorConfig.backend === 'weaviate_embedded' && (
                      <div className="p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] text-sm text-[var(--color-text-secondary)]">
                        Weaviate Embedded 模式将使用内置向量引擎，无需配置主机和端口。
                      </div>
                    )}
                  </div>
                  <div className="flex justify-end mt-6">
                    <Button
                      onClick={handleSave}
                      loading={saveStatus === 'saving'}
                      disabled={!isBackendRunning}
                    >
                      {saveStatus === 'saved' ? '已保存' : '保存配置'}
                    </Button>
                  </div>
                </CardBody>
              </Card>
            </div>
          )}

          {activeSection === 'graph' && (
            <div className="space-y-6">
              {/* 图数据库状态 */}
              <Card>
                <CardBody>
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold">图数据库状态</h3>
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-3 h-3 rounded-full ${
                          graphHealth?.connected
                            ? 'bg-green-500'
                            : graphHealth?.graph_enabled
                            ? 'bg-red-500'
                            : 'bg-gray-400'
                        }`}
                      />
                      <span className="text-sm">
                        {graphHealth?.connected
                          ? '已连接'
                          : graphHealth?.graph_enabled
                          ? '连接失败'
                          : '未启用'}
                      </span>
                    </div>
                  </div>
                  {graphHealth?.message && (
                    <p className="text-sm text-[var(--color-text-secondary)]">{graphHealth.message}</p>
                  )}
                  {graphStats?.connected && graphStats.libraries && (
                    <div className="grid grid-cols-4 gap-4 mt-4">
                      {Object.entries(graphStats.libraries).map(([name, stats]) => (
                        <div
                          key={name}
                          className="p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]"
                        >
                          <div className="text-xs text-[var(--color-text-tertiary)] uppercase">{name}</div>
                          <div className="text-lg font-semibold">{stats.entity_count}</div>
                          <div className="text-xs text-[var(--color-text-secondary)]">
                            实体 / {stats.relation_count} 关系
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardBody>
              </Card>

              {/* 图数据库配置 */}
              <Card>
                <CardBody>
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h3 className="text-lg font-semibold">图数据库配置</h3>
                      <p className="text-sm text-[var(--color-text-secondary)]">
                        SQLite + Weaviate 语义图数据库，支持语义检索和图遍历
                      </p>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <span className="text-sm font-medium">数据库路径</span>
                          <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                            data/graph.db
                          </p>
                        </div>
                        <div>
                          <span className="text-sm font-medium">状态</span>
                          <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                            {graphHealth?.connected ? '已连接' : '未连接'}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
                      <h4 className="text-sm font-medium mb-3">图数据库功能</h4>
                      <div className="grid grid-cols-3 gap-4">
                        <div className="text-center">
                          <div className="text-lg font-semibold">
                            {Object.values(graphStats?.libraries || {}).reduce((sum, lib) => sum + (lib.entity_count || 0), 0)}
                          </div>
                          <div className="text-xs text-[var(--color-text-tertiary)]">节点</div>
                        </div>
                        <div className="text-center">
                          <div className="text-lg font-semibold">
                            {Object.values(graphStats?.libraries || {}).reduce((sum, lib) => sum + (lib.relation_count || 0), 0)}
                          </div>
                          <div className="text-xs text-[var(--color-text-tertiary)]">边</div>
                        </div>
                        <div className="text-center">
                          <div className="text-lg font-semibold">
                            {graphStats?.graph_enabled ? '启用' : '禁用'}
                          </div>
                          <div className="text-xs text-[var(--color-text-tertiary)]">图存储</div>
                        </div>
                      </div>
                    </div>

                    <div className="flex gap-2 flex-wrap">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={async () => {
                          try {
                            const result = await api.getGraphStats() as unknown as typeof graphStats;
                            if (result) setGraphStats(result);
                          } catch {
                            console.error('获取图统计失败');
                          }
                        }}
                      >
                        刷新统计
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={async () => {
                          try {
                            const health = await api.getGraphHealth() as typeof graphHealth;
                            if (health) setGraphHealth(health);
                          } catch {
                            console.error('获取图健康状态失败');
                          }
                        }}
                      >
                        健康检查
                      </Button>
                    </div>
                  </div>
                </CardBody>
              </Card>

              <div className="flex justify-end mt-6">
                <Button
                  onClick={handleSave}
                  loading={saveStatus === 'saving'}
                  disabled={!isBackendRunning}
                >
                  {saveStatus === 'saved' ? '已保存' : '保存配置'}
                </Button>
              </div>
            </div>
          )}

          {activeSection === 'llm' && (
            <div className="space-y-6">
              {/* 默认模型配置 */}
              <Card>
                <CardBody>
                  <div className="mb-4">
                    <h3 className="text-lg font-semibold">默认模型</h3>
                    <p className="text-sm text-[var(--color-text-secondary)]">
                      用于日常对话的默认模型配置（始终启用）
                    </p>
                  </div>
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">模型提供商</label>
                        <select
                          value={modelsConfig.main.provider}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              main: { ...prev.main, provider: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        >
                          <option value="ollama">Ollama (本地)</option>
                          <option value="vllm">vLLM</option>
                          <option value="openai">OpenAI</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">模型名称</label>
                        <input
                          type="text"
                          value={modelsConfig.main.model}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              main: { ...prev.main, model: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="llama3.2:3b"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">主机地址</label>
                        <input
                          type="text"
                          value={modelsConfig.main.host}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              main: { ...prev.main, host: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="http://localhost:11434"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">API Key</label>
                        <input
                          type="password"
                          value={modelsConfig.main.apiKey}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              main: { ...prev.main, apiKey: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="可选，用于 OpenAI 等需要认证的提供商"
                        />
                      </div>
                    </div>
                  </div>
                </CardBody>
              </Card>

              {/* 记忆管理模型配置 */}
              <Card>
                <CardBody>
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h3 className="text-lg font-semibold">记忆管理模型</h3>
                      <p className="text-sm text-[var(--color-text-secondary)]">
                        用于记忆归档、记忆合并等后台任务（未启用时使用默认模型）
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-[var(--color-text-secondary)]">启用</span>
                      <button
                        onClick={() =>
                          setModelsConfig((prev) => ({
                            ...prev,
                            memory: { ...prev.memory, enabled: !prev.memory.enabled },
                          }))
                        }
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          modelsConfig.memory.enabled
                            ? 'bg-[var(--color-accent)]'
                            : 'bg-[var(--color-border)]'
                        }`}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            modelsConfig.memory.enabled ? 'translate-x-6' : 'translate-x-1'
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">模型提供商</label>
                        <select
                          value={modelsConfig.memory.provider}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              memory: { ...prev.memory, provider: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        >
                          <option value="ollama">Ollama (本地)</option>
                          <option value="vllm">vLLM</option>
                          <option value="openai">OpenAI</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">模型名称</label>
                        <input
                          type="text"
                          value={modelsConfig.memory.model}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              memory: { ...prev.memory, model: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="llama3.2:3b"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">主机地址</label>
                        <input
                          type="text"
                          value={modelsConfig.memory.host}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              memory: { ...prev.memory, host: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="http://localhost:11434"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">API Key</label>
                        <input
                          type="password"
                          value={modelsConfig.memory.apiKey}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              memory: { ...prev.memory, apiKey: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="可选，用于 OpenAI 等需要认证的提供商"
                        />
                      </div>
                    </div>
                  </div>
                </CardBody>
              </Card>

              {/* 摘要模型配置 */}
              <Card>
                <CardBody>
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <h3 className="text-lg font-semibold">摘要模型</h3>
                      <p className="text-sm text-[var(--color-text-secondary)]">
                        用于对话摘要生成（未启用时使用默认模型）
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-[var(--color-text-secondary)]">启用</span>
                      <button
                        onClick={() =>
                          setModelsConfig((prev) => ({
                            ...prev,
                            summary: { ...prev.summary, enabled: !prev.summary.enabled },
                          }))
                        }
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          modelsConfig.summary.enabled
                            ? 'bg-[var(--color-accent)]'
                            : 'bg-[var(--color-border)]'
                        }`}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            modelsConfig.summary.enabled ? 'translate-x-6' : 'translate-x-1'
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">模型提供商</label>
                        <select
                          value={modelsConfig.summary.provider}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              summary: { ...prev.summary, provider: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        >
                          <option value="ollama">Ollama (本地)</option>
                          <option value="vllm">vLLM</option>
                          <option value="openai">OpenAI</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">模型名称</label>
                        <input
                          type="text"
                          value={modelsConfig.summary.model}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              summary: { ...prev.summary, model: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="llama3.2:3b"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">主机地址</label>
                        <input
                          type="text"
                          value={modelsConfig.summary.host}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              summary: { ...prev.summary, host: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="http://localhost:11434"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">API Key</label>
                        <input
                          type="password"
                          value={modelsConfig.summary.apiKey}
                          onChange={(e) =>
                            setModelsConfig((prev) => ({
                              ...prev,
                              summary: { ...prev.summary, apiKey: e.target.value },
                            }))
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="可选，用于 OpenAI 等需要认证的提供商"
                        />
                      </div>
                    </div>
                  </div>
                </CardBody>
              </Card>

              {/* 保存按钮 */}
              <div className="flex justify-end">
                <Button
                  onClick={handleSave}
                  loading={saveStatus === 'saving'}
                  disabled={!isBackendRunning}
                >
                  {saveStatus === 'saved' ? '已保存' : '保存配置'}
                </Button>
              </div>
            </div>
          )}

          {activeSection === 'audio' && (
            <div className="space-y-6">
              {/* 音频文件管理 */}
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
                          onChange={handleAudioUpload}
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
                                    onClick={() => handlePlayAudio(file.name)}
                                    className="text-[var(--color-accent)] hover:underline mr-3"
                                  >
                                    {playingAudio === file.name ? '停止' : '播放'}
                                  </button>
                                  <button
                                    onClick={() => handleDeleteAudio(file.name)}
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
                        src={api.getAudioFileUrl(playingAudio)}
                        autoPlay
                        onEnded={() => setPlayingAudio(null)}
                        className="hidden"
                      />
                    )}
                  </div>
                </CardBody>
              </Card>

              {/* VoiceWorkStation 连接状态 */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">VoiceWorkStation 状态</h3>
                  <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                    语音工作站服务连接状态（端口 8200）
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
                      <div className="text-sm font-medium">VoiceWorkStation 服务</div>
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

              {/* TTS 基础配置 */}
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
                            setAudioConfig({ ...audioConfig, ref_audio_path: e.target.value })
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
                            setAudioConfig({ ...audioConfig, ref_text: e.target.value })
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
                          max="2"
                          step="0.1"
                          value={audioConfig.speed}
                          onChange={(e) =>
                            setAudioConfig({ ...audioConfig, speed: parseFloat(e.target.value) })
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
                            setAudioConfig({
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

              {/* 功能开关 */}
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
                          setAudioConfig({
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
                          setAudioConfig({
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

              {/* 情感语音配置 */}
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
                                setAudioConfig({
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
                                setAudioConfig({
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

              {/* VAD 语音检测配置 */}
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
                              setVadConfig({
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
                              setVadConfig({
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
                              setVadConfig({
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
                            setVadConfig({
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
                            setVadConfig({
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
                            setVadConfig({
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
                            setVadConfig({
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
                            setVadConfig({
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

              {/* SenseVoice 流式模式配置 */}
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
                          setSensevoiceStreamingConfig({
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
                          setSensevoiceStreamingConfig({
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
                          setSensevoiceStreamingConfig({
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

              {/* LLM 自适应轮询配置 */}
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
                          setAdaptivePollingConfig({
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
                            setAdaptivePollingConfig({
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

              {/* Agent 打断用户配置 */}
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
                          setVadConfig({
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
                              setVadConfig({
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
                              setVadConfig({
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
                              setVadConfig({
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

              {/* 用户打断 Agent 配置 */}
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
                          setFirewallV3Config({
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
                                  setFirewallV3Config({
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
                                  setFirewallV3Config({
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
                                setFirewallV3Config({
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
                <Button onClick={handleSave} loading={saveStatus === 'saving'}>
                  {saveStatus === 'saved' ? '已保存' : '保存配置'}
                </Button>
              </div>
            </div>
          )}

          {activeSection === 'live2d' && (
            <div className="space-y-6">
              {/* 虚拟形象类型选择 */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">虚拟形象类型</h3>
                  <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                    选择在聊天页面显示的虚拟形象类型
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setAvatarType('none')}
                      className={`flex-1 p-3 rounded-[var(--radius-md)] border transition-colors ${
                        avatarType === 'none'
                          ? 'border-[var(--color-accent)] bg-[var(--color-accent-light)]'
                          : 'border-[var(--color-border)] hover:border-[var(--color-accent)]'
                      }`}
                    >
                      <div className="text-center">
                        <svg className="w-6 h-6 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                        </svg>
                        <span className="text-sm font-medium">无</span>
                      </div>
                    </button>
                    <button
                      onClick={() => setAvatarType('live2d')}
                      className={`flex-1 p-3 rounded-[var(--radius-md)] border transition-colors ${
                        avatarType === 'live2d'
                          ? 'border-[var(--color-accent)] bg-[var(--color-accent-light)]'
                          : 'border-[var(--color-border)] hover:border-[var(--color-accent)]'
                      }`}
                    >
                      <div className="text-center">
                        <svg className="w-6 h-6 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <span className="text-sm font-medium">Live2D</span>
                      </div>
                    </button>
                    <button
                      onClick={() => setAvatarType('vrm')}
                      className={`flex-1 p-3 rounded-[var(--radius-md)] border transition-colors ${
                        avatarType === 'vrm'
                          ? 'border-[var(--color-accent)] bg-[var(--color-accent-light)]'
                          : 'border-[var(--color-border)] hover:border-[var(--color-accent)]'
                      }`}
                    >
                      <div className="text-center">
                        <svg className="w-6 h-6 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                        </svg>
                        <span className="text-sm font-medium">VRM 3D</span>
                      </div>
                    </button>
                  </div>
                </CardBody>
              </Card>

              {/* Live2D 配置 */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">Live2D 虚拟形象</h3>
                  <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                    在聊天页面显示 Live2D 虚拟形象，支持口型同步
                  </p>
                  <div className="space-y-4">
                    <div>
                      <label className="text-sm font-medium mb-2 block">模型路径</label>
                      <input
                        type="text"
                        value={live2dSettings.modelPath}
                        onChange={(e) => setLive2DSettings({ modelPath: e.target.value })}
                        placeholder="/models/shizuku/shizuku.model.json"
                        className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                      />
                      <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                        模型文件相对于 public 目录的路径
                      </p>
                    </div>

                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">缩放</label>
                        <input
                          type="number"
                          step="0.05"
                          value={live2dSettings.scale}
                          onChange={(e) => setLive2DSettings({ scale: parseFloat(e.target.value) || 0.3 })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">X 偏移</label>
                        <input
                          type="number"
                          value={live2dSettings.xOffset}
                          onChange={(e) => setLive2DSettings({ xOffset: parseInt(e.target.value) || 0 })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">Y 偏移</label>
                        <input
                          type="number"
                          value={live2dSettings.yOffset}
                          onChange={(e) => setLive2DSettings({ yOffset: parseInt(e.target.value) || 0 })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="flex items-center justify-between p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                        <span className="text-sm">口型同步</span>
                        <button
                          onClick={() => setLive2DSettings({ lipSync: !live2dSettings.lipSync })}
                          className={`w-10 h-5 rounded-full transition-colors ${
                            live2dSettings.lipSync ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                          }`}
                        >
                          <div
                            className={`w-4 h-4 rounded-full bg-white transition-transform ${
                              live2dSettings.lipSync ? 'translate-x-5' : 'translate-x-0.5'
                            }`}
                          />
                        </button>
                      </div>
                      <div className="flex items-center justify-between p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                        <span className="text-sm">空闲动作</span>
                        <button
                          onClick={() => setLive2DSettings({ idleMotion: !live2dSettings.idleMotion })}
                          className={`w-10 h-5 rounded-full transition-colors ${
                            live2dSettings.idleMotion ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                          }`}
                        >
                          <div
                            className={`w-4 h-4 rounded-full bg-white transition-transform ${
                              live2dSettings.idleMotion ? 'translate-x-5' : 'translate-x-0.5'
                            }`}
                          />
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">最小宽度</label>
                        <input
                          type="number"
                          value={live2dSettings.minWidth}
                          onChange={(e) => setLive2DSettings({ minWidth: parseInt(e.target.value) || 200 })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">最大宽度</label>
                        <input
                          type="number"
                          value={live2dSettings.maxWidth}
                          onChange={(e) => setLive2DSettings({ maxWidth: parseInt(e.target.value) || 400 })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                    </div>
                  </div>
                </CardBody>
              </Card>

              {/* VRM 3D 配置 */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">VRM 3D 虚拟形象</h3>
                  <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                    在聊天页面显示 VRM 3D 虚拟形象，支持口型同步和视线追踪
                  </p>
                  <div className="space-y-4">
                    <div>
                      <label className="text-sm font-medium mb-2 block">模型路径</label>
                      <input
                        type="text"
                        value={vrmSettings.modelPath}
                        onChange={(e) => setVRMSettings({ modelPath: e.target.value })}
                        placeholder="/models/avatar.vrm"
                        className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                      />
                      <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                        VRM 模型文件相对于 public 目录的路径
                      </p>
                    </div>

                    <div className="grid grid-cols-4 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">缩放</label>
                        <input
                          type="number"
                          step="0.1"
                          value={vrmSettings.scale}
                          onChange={(e) => setVRMSettings({ scale: parseFloat(e.target.value) || 1.0 })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">X 位置</label>
                        <input
                          type="number"
                          step="0.1"
                          value={vrmSettings.position3d[0]}
                          onChange={(e) => setVRMSettings({ position3d: [parseFloat(e.target.value) || 0, vrmSettings.position3d[1], vrmSettings.position3d[2]] })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">Y 位置</label>
                        <input
                          type="number"
                          step="0.1"
                          value={vrmSettings.position3d[1]}
                          onChange={(e) => setVRMSettings({ position3d: [vrmSettings.position3d[0], parseFloat(e.target.value) || 0, vrmSettings.position3d[2]] })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">Z 位置</label>
                        <input
                          type="number"
                          step="0.1"
                          value={vrmSettings.position3d[2]}
                          onChange={(e) => setVRMSettings({ position3d: [vrmSettings.position3d[0], vrmSettings.position3d[1], parseFloat(e.target.value) || 0] })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-4">
                      <div className="flex items-center justify-between p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                        <span className="text-sm">口型同步</span>
                        <button
                          onClick={() => setVRMSettings({ lipSync: !vrmSettings.lipSync })}
                          className={`w-10 h-5 rounded-full transition-colors ${
                            vrmSettings.lipSync ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                          }`}
                        >
                          <div
                            className={`w-4 h-4 rounded-full bg-white transition-transform ${
                              vrmSettings.lipSync ? 'translate-x-5' : 'translate-x-0.5'
                            }`}
                          />
                        </button>
                      </div>
                      <div className="flex items-center justify-between p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                        <span className="text-sm">空闲动画</span>
                        <button
                          onClick={() => setVRMSettings({ idleAnimation: !vrmSettings.idleAnimation })}
                          className={`w-10 h-5 rounded-full transition-colors ${
                            vrmSettings.idleAnimation ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                          }`}
                        >
                          <div
                            className={`w-4 h-4 rounded-full bg-white transition-transform ${
                              vrmSettings.idleAnimation ? 'translate-x-5' : 'translate-x-0.5'
                            }`}
                          />
                        </button>
                      </div>
                      <div className="flex items-center justify-between p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                        <span className="text-sm">视线追踪</span>
                        <button
                          onClick={() => setVRMSettings({ lookAtMouse: !vrmSettings.lookAtMouse })}
                          className={`w-10 h-5 rounded-full transition-colors ${
                            vrmSettings.lookAtMouse ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                          }`}
                        >
                          <div
                            className={`w-4 h-4 rounded-full bg-white transition-transform ${
                              vrmSettings.lookAtMouse ? 'translate-x-5' : 'translate-x-0.5'
                            }`}
                          />
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">最小宽度</label>
                        <input
                          type="number"
                          value={vrmSettings.minWidth}
                          onChange={(e) => setVRMSettings({ minWidth: parseInt(e.target.value) || 200 })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">最大宽度</label>
                        <input
                          type="number"
                          value={vrmSettings.maxWidth}
                          onChange={(e) => setVRMSettings({ maxWidth: parseInt(e.target.value) || 400 })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                    </div>
                  </div>
                </CardBody>
              </Card>

              <div className="flex justify-end mt-6">
                <Button onClick={handleSave} loading={saveStatus === 'saving'}>
                  {saveStatus === 'saved' ? '已保存' : '保存配置'}
                </Button>
              </div>
            </div>
          )}

          {activeSection === 'live' && (
            <div className="space-y-6">
              {/* 直播客户端状态 */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">直播客户端状态</h3>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-3 h-3 rounded-full ${liveClientStatus.connected ? 'bg-green-500' : 'bg-gray-400'}`} />
                      <span className="text-sm font-medium">
                        {liveClientStatus.connected ? '已连接' : '未连接'}
                      </span>
                      {liveClientStatus.connected && liveClientStatus.client_id && (
                        <span className="text-xs text-[var(--color-text-tertiary)]">
                          ID: {liveClientStatus.client_id.slice(0, 8)}...
                        </span>
                      )}
                    </div>
                    <Button
                      onClick={async () => {
                        if (liveClientStatus.connected && liveClientStatus.client_id) {
                          await api.disconnectLiveClient(liveClientStatus.client_id);
                          setLiveClientStatus({ connected: false });
                        }
                      }}
                      disabled={!liveClientStatus.connected}
                      variant="ghost"
                      size="sm"
                    >
                      断开连接
                    </Button>
                  </div>
                </CardBody>
              </Card>

              {/* 弹幕 WebSocket 配置 */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">弹幕 WebSocket 配置</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="text-sm font-medium mb-2 block">WebSocket 端点</label>
                      <input
                        type="text"
                        value={danmakuConfig.websocket.endpoint}
                        onChange={(e) =>
                          setDanmakuConfig({
                            ...danmakuConfig,
                            websocket: { ...danmakuConfig.websocket, endpoint: e.target.value },
                          })
                        }
                        className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        placeholder="/ws/live"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-2 block">最大连接数</label>
                      <input
                        type="number"
                        value={danmakuConfig.websocket.max_connections}
                        onChange={(e) =>
                          setDanmakuConfig({
                            ...danmakuConfig,
                            websocket: { ...danmakuConfig.websocket, max_connections: parseInt(e.target.value) || 100 },
                          })
                        }
                        className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                      />
                    </div>
                  </div>
                </CardBody>
              </Card>

              {/* 弹幕数据源配置 */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">弹幕数据源</h3>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <label className="text-sm font-medium">B站弹幕</label>
                        <p className="text-xs text-[var(--color-text-tertiary)]">接入 B站 直播弹幕</p>
                      </div>
                      <button
                        onClick={() =>
                          setDanmakuConfig({
                            ...danmakuConfig,
                            sources: {
                              ...danmakuConfig.sources,
                              bilibili: { ...danmakuConfig.sources.bilibili, enabled: !danmakuConfig.sources.bilibili.enabled },
                            },
                          })
                        }
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          danmakuConfig.sources.bilibili.enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                        }`}
                      >
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${danmakuConfig.sources.bilibili.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
                      </button>
                    </div>
                    {danmakuConfig.sources.bilibili.enabled && (
                      <div>
                        <label className="text-sm font-medium mb-2 block">B站 WebSocket 地址</label>
                        <input
                          type="text"
                          value={danmakuConfig.sources.bilibili.websocket_url}
                          onChange={(e) =>
                            setDanmakuConfig({
                              ...danmakuConfig,
                              sources: {
                                ...danmakuConfig.sources,
                                bilibili: { ...danmakuConfig.sources.bilibili, websocket_url: e.target.value },
                              },
                            })
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="ws://localhost:8080"
                        />
                      </div>
                    )}

                    <div className="flex items-center justify-between">
                      <div>
                        <label className="text-sm font-medium">RDF 弹幕</label>
                        <p className="text-xs text-[var(--color-text-tertiary)]">接入 RDF 直播弹幕</p>
                      </div>
                      <button
                        onClick={() =>
                          setDanmakuConfig({
                            ...danmakuConfig,
                            sources: {
                              ...danmakuConfig.sources,
                              rdf: { ...danmakuConfig.sources.rdf, enabled: !danmakuConfig.sources.rdf.enabled },
                            },
                          })
                        }
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          danmakuConfig.sources.rdf.enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                        }`}
                      >
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${danmakuConfig.sources.rdf.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
                      </button>
                    </div>
                    {danmakuConfig.sources.rdf.enabled && (
                      <div>
                        <label className="text-sm font-medium mb-2 block">RDF WebSocket 地址</label>
                        <input
                          type="text"
                          value={danmakuConfig.sources.rdf.websocket_url}
                          onChange={(e) =>
                            setDanmakuConfig({
                              ...danmakuConfig,
                              sources: {
                                ...danmakuConfig.sources,
                                rdf: { ...danmakuConfig.sources.rdf, websocket_url: e.target.value },
                              },
                            })
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="ws://localhost:9898"
                        />
                      </div>
                    )}
                  </div>
                </CardBody>
              </Card>

              {/* 弹幕防火墙配置 */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">弹幕防火墙</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="text-sm font-medium mb-2 block">LLM 模型</label>
                      <input
                        type="text"
                        value={firewallConfig.llm.default_model}
                        onChange={(e) =>
                          setFirewallConfig({
                            ...firewallConfig,
                            llm: { ...firewallConfig.llm, default_model: e.target.value },
                          })
                        }
                        className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        placeholder="qwen2.5:latest"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-2 block">LLM 超时 (ms)</label>
                      <input
                        type="number"
                        value={firewallConfig.decision.timeout_ms}
                        onChange={(e) =>
                          setFirewallConfig({
                            ...firewallConfig,
                            decision: { ...firewallConfig.decision, timeout_ms: parseInt(e.target.value) || 5000 },
                          })
                        }
                        className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                      />
                    </div>

                    <div className="flex items-center justify-between">
                      <div>
                        <label className="text-sm font-medium">黑名单</label>
                        <p className="text-xs text-[var(--color-text-tertiary)]">启用用户黑名单过滤</p>
                      </div>
                      <button
                        onClick={() =>
                          setFirewallConfig({
                            ...firewallConfig,
                            blocking: { ...firewallConfig.blocking, blacklist_enabled: !firewallConfig.blocking.blacklist_enabled },
                          })
                        }
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                          firewallConfig.blocking.blacklist_enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                        }`}
                      >
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${firewallConfig.blocking.blacklist_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
                      </button>
                    </div>

                    {firewallConfig.blocking.blacklist_enabled && (
                      <div>
                        <label className="text-sm font-medium mb-2 block">黑名单 UID 列表</label>
                        <div className="flex gap-2 mb-2">
                          <input
                            type="text"
                            value={newBlacklistUid}
                            onChange={(e) => setNewBlacklistUid(e.target.value)}
                            className="flex-1 px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                            placeholder="输入 UID"
                          />
                          <Button
                            onClick={() => {
                              if (newBlacklistUid.trim()) {
                                setFirewallConfig({
                                  ...firewallConfig,
                                  blocking: {
                                    ...firewallConfig.blocking,
                                    blacklist: [...firewallConfig.blocking.blacklist, newBlacklistUid.trim()],
                                  },
                                });
                                setNewBlacklistUid('');
                              }
                            }}
                            size="sm"
                          >
                            添加
                          </Button>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {firewallConfig.blocking.blacklist.map((uid) => (
                            <span
                              key={uid}
                              className="inline-flex items-center gap-1 px-2 py-1 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] text-sm"
                            >
                              {uid}
                              <button
                                onClick={() =>
                                  setFirewallConfig({
                                    ...firewallConfig,
                                    blocking: {
                                      ...firewallConfig.blocking,
                                      blacklist: firewallConfig.blocking.blacklist.filter((u) => u !== uid),
                                    },
                                  })
                                }
                                className="text-[var(--color-text-tertiary)] hover:text-red-500"
                              >
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </CardBody>
              </Card>

              <div className="flex justify-end">
                <Button onClick={handleSave} loading={saveStatus === 'saving'}>
                  {saveStatus === 'saved' ? '已保存' : '保存配置'}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
