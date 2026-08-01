import { useState, useEffect, useCallback, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { CxfcPlugin, CxfcSkill } from '../api/client';
import { cn } from '../lib/utils';
import { useThemeStore } from '../store/themeStore';
import { useSettingsStore } from '../store/settingsStore';
import { PageHeader } from '@/components/business/layout';
import { AvatarManager } from '@/components/business/avatar/avatar-manager';
import type { SettingSection } from './settings/types';
import { AppearanceCard } from './settings/cards/AppearanceCard';
import { ServiceCard } from './settings/cards/ServiceCard';
import { VectorCard } from './settings/cards/VectorCard';
import { GraphCard } from './settings/cards/GraphCard';
import { LlmCard } from './settings/cards/LlmCard';
import { PluginCard } from './settings/cards/PluginCard';
import { AudioCard } from './settings/cards/AudioCard';
import { Live2DCard } from './settings/cards/Live2DCard';
import { LiveCard } from './settings/cards/LiveCard';

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
    description: '配置图数据库',
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
  {
    id: 'plugin',
    title: '插件管理',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
      </svg>
    ),
    description: '管理CXFC插件连接、Skills和事件',
  },
];

export function SettingsPage() {
  const [activeSection, setActiveSection] = useState<'appearance' | 'service' | 'audio' | 'live' | 'live2d' | 'vector' | 'graph' | 'llm' | 'plugin'>(
    'appearance'
  );
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [logs, setLogs] = useState('');
  const [isBackendRunning, setIsBackendRunning] = useState(false);
  const [isControlServiceReady, setIsControlServiceReady] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [showAvatarManager, setShowAvatarManager] = useState<'live2d' | 'vrm' | null>(null);

  const [plugins, setPlugins] = useState<CxfcPlugin[]>([]);
  const [skills, setSkills] = useState<CxfcSkill[]>([]);
  const [showConnectDialog, setShowConnectDialog] = useState(false);
  const [connectHost, setConnectHost] = useState('localhost');
  const [connectPort, setConnectPort] = useState(8081);
  const [speedMax, setSpeedMax] = useState(3);

  const loadPlugins = async () => {
    try {
      const data = await api.getCxfcPlugins();
      setPlugins(data);
    } catch { /* ignore */ }
  };

  const loadSkills = async () => {
    try {
      const data = await api.getCxfcSkills();
      setSkills(data);
    } catch { /* ignore */ }
  };

  const handleScanPlugins = async () => {
    try {
      const result = await api.discoverCxfcPlugins(true);
      if (result.remote && result.remote.length > 0) {
        alert(`发现 ${result.remote.length} 个局域网插件`);
      } else {
        alert('未发现局域网插件');
      }
      loadPlugins();
    } catch { /* ignore */ }
  };

  const handleConnectPlugin = async () => {
    try {
      await api.connectCxfcPlugin(connectHost, connectPort);
      setShowConnectDialog(false);
      loadPlugins();
      loadSkills();
    } catch {
      alert('连接失败');
    }
  };

  const handleDisconnectPlugin = async (pluginId: string) => {
    try {
      await api.disconnectCxfcPlugin(pluginId);
      loadPlugins();
      loadSkills();
    } catch { /* ignore */ }
  };

  const handleRefreshPlugin = async (pluginId: string) => {
    try {
      await api.refreshCxfcPlugin(pluginId);
      loadPlugins();
      loadSkills();
    } catch { /* ignore */ }
  };

  const { avatarType, setAvatarType, limits } = useSettingsStore();
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
      const apiUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
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
      const apiUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
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

  type GatewayServicesConfig = {
    monolith: { url: string; http_url: string; timeout: number; status: string };
  };
  const [, setGatewayServicesConfig] = useState<GatewayServicesConfig>({
    monolith: { url: 'ws://127.0.0.1:8000/ws', http_url: 'http://127.0.0.1:8000', timeout: 30, status: '集成' },
  });

  useEffect(() => {
    const loadGatewayConfig = async () => {
      if (!isBackendRunning) return;
      try {
        const data = await api.getServiceConfig() as { status?: string; config?: GatewayServicesConfig };
        if (data.status === 'success' && data.config) {
          setGatewayServicesConfig(data.config);
        }
      } catch (error) {
        console.error('Failed to load Gateway config:', error);
      }
    };
    loadGatewayConfig();
  }, [isBackendRunning]);

  const [vectorConfig, setVectorConfig] = useState({
    backend: 'weaviate',
    vectorSize: 768,
    dbPath: 'data/chroma_db',
    collectionName: 'memory_vectors',
    weaviateHost: 'localhost',
    weaviatePort: 8090,
    qdrantHost: 'localhost',
    qdrantPort: 6333,
    embeddingProvider: 'ollama',
    embeddingModel: 'nomic-embed-text',
    embeddingApiBase: '',
    embeddingApiKey: '',
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
    graph_backend: 'sqlite',
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
    if (limits?.speed_max) {
      setSpeedMax(limits.speed_max);
    }
  }, [limits]);

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
          graph_libraries?: typeof graphConfig.graph_libraries;
        } };
        if (cfg.status === 'success' && cfg.config) {
          setGraphConfig({
            graph_enabled: cfg.config.graph_enabled ?? false,
            graph_backend: cfg.config.graph_backend ?? 'sqlite',
            graph_libraries: cfg.config.graph_libraries ?? graphConfig.graph_libraries,
          });
        }
        if (healthData && typeof healthData === 'object') {
          // healthData 来自 /api/graph/health: {database, semantic, overall}
          // 需转换为 GraphCard 期望的 {status, graph_enabled, connected, message}
          // 详见 .trae/documents/20260720_模块0_图数据库按需创建.md §五
          const health = healthData as { database?: string; semantic?: string; overall?: string };
          if (health.overall) {
            setGraphHealth({
              status: health.overall,
              graph_enabled: true,
              connected: health.overall === 'healthy',
              message: `database: ${health.database ?? 'unknown'}, semantic: ${health.semantic ?? 'unknown'}`,
            });
          }
        }
        // statsData 来自 /api/graph/status: {connected, graph_enabled, message, libraries, database_path}
        // 直接是 GraphStats 格式，不再期望 {status, graph_status} 嵌套
        const stats = statsData as typeof graphStats;
        if (stats && stats.libraries) {
          setGraphStats(stats);
        }
      } catch (error) {
        console.error('Failed to load graph config:', error);
      }
    };
    loadGraphConfig();
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
          embeddingProvider: (vec.embedding_provider as string) ?? 'ollama',
          embeddingModel: (vec.embedding_model as string) ?? 'nomic-embed-text',
          embeddingApiBase: (vec.embedding_api_base as string) ?? '',
          embeddingApiKey: (vec.embedding_api_key as string) ?? '',
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

  useEffect(() => {
    if (activeSection === 'plugin') {
      loadPlugins();
      loadSkills();
    }
  }, [activeSection]);

  const handleStartBackend = async () => {
    setIsProcessing(true);
    try {
      const response = await fetch('http://127.0.0.1:8000/health');
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
          await api.updateConfig('vector', {
            backend: vectorConfig.backend,
            vector_size: vectorConfig.vectorSize,
            weaviate_host: vectorConfig.weaviateHost,
            weaviate_port: vectorConfig.weaviatePort,
            embedding_provider: vectorConfig.embeddingProvider,
            embedding_model: vectorConfig.embeddingModel,
            embedding_api_base: vectorConfig.embeddingApiBase,
            embedding_api_key: vectorConfig.embeddingApiKey,
          });
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

  const handleDisconnectLive = async () => {
    if (liveClientStatus.connected && liveClientStatus.client_id) {
      await api.disconnectLiveClient(liveClientStatus.client_id);
      setLiveClientStatus({ connected: false });
    }
  };

  const handleRefreshGraphStats = async () => {
    try {
      // 使用 getGraphStatus（而非 getGraphStats）：返回 GraphCard 期望的
      // {connected, graph_enabled, message, libraries, database_path} 格式
      // 详见 .trae/documents/20260720_模块0_图数据库按需创建.md §五
      const result = await api.getGraphStatus() as unknown as typeof graphStats;
      if (result) setGraphStats(result);
    } catch {
      console.error('获取图统计失败');
    }
  };

  const handleGraphHealthCheck = async () => {
    try {
      // /api/graph/health 返回 {database, semantic, overall}，需转换为
      // GraphCard 期望的 {status, graph_enabled, connected, message}
      const raw = await api.getGraphHealth() as { database?: string; semantic?: string; overall?: string };
      if (raw) {
        setGraphHealth({
          status: raw.overall ?? 'unknown',
          graph_enabled: true,
          connected: raw.overall === 'healthy',
          message: `database: ${raw.database ?? 'unknown'}, semantic: ${raw.semantic ?? 'unknown'}`,
        });
      }
    } catch {
      console.error('获取图健康状态失败');
    }
  };

  return (
    <div className={`max-w-6xl mx-auto h-full overflow-y-auto px-6 py-6 ${themeTransition ? 'transition-colors duration-300' : ''}`}>
      <PageHeader title="系统设置" description="配置系统外观、服务和行为" />

      <div className="flex gap-6">
        <nav className="w-56 flex-shrink-0 space-y-1">
          {sections.map((section) => (
            <button
              key={section.id}
              onClick={() => setActiveSection(section.id as typeof activeSection)}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-lg)] text-sm font-medium transition-all text-left',
                activeSection === section.id
                  ? 'bg-[var(--glass-active-bg)] text-[var(--color-text-primary)]'
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--glass-hover-bg)] hover:text-[var(--color-text-primary)]'
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
            <AppearanceCard
              theme={theme}
              onThemeChange={handleThemeChange}
              selectedAccent={selectedAccent}
              onSelectedAccentChange={setSelectedAccent}
              cn={cn}
            />
          )}

          {activeSection === 'service' && (
            <ServiceCard
              isBackendRunning={isBackendRunning}
              isProcessing={isProcessing}
              backendStatus={backendStatus}
              logs={logs}
              onRestartBackend={handleRestartBackend}
              onStopBackend={handleStopBackend}
              onStartBackend={handleStartBackend}
            />
          )}

          {activeSection === 'vector' && (
            <VectorCard
              vectorConfig={vectorConfig}
              onVectorConfigChange={setVectorConfig}
              onSave={handleSave}
              saveStatus={saveStatus}
              isBackendRunning={isBackendRunning}
            />
          )}

          {activeSection === 'graph' && (
            <GraphCard
              graphHealth={graphHealth}
              graphStats={graphStats}
              onSave={handleSave}
              saveStatus={saveStatus}
              isBackendRunning={isBackendRunning}
              onRefreshStats={handleRefreshGraphStats}
              onHealthCheck={handleGraphHealthCheck}
            />
          )}

          {activeSection === 'llm' && (
            <LlmCard
              modelsConfig={modelsConfig}
              onModelsConfigChange={setModelsConfig}
              llmParams={llmParams}
              onLlmParamsChange={setLlmParams}
              onSave={handleSave}
              saveStatus={saveStatus}
              isBackendRunning={isBackendRunning}
            />
          )}

          {activeSection === 'plugin' && (
            <PluginCard
              plugins={plugins}
              skills={skills}
              showConnectDialog={showConnectDialog}
              connectHost={connectHost}
              connectPort={connectPort}
              onScanPlugins={handleScanPlugins}
              onConnectPlugin={handleConnectPlugin}
              onDisconnectPlugin={handleDisconnectPlugin}
              onRefreshPlugin={handleRefreshPlugin}
              onShowConnectDialogChange={setShowConnectDialog}
              onConnectHostChange={setConnectHost}
              onConnectPortChange={setConnectPort}
            />
          )}

          {activeSection === 'audio' && (
            <AudioCard
              audioFiles={audioFiles}
              uploadingFile={uploadingFile}
              onAudioUploadChange={handleAudioUpload}
              playingAudio={playingAudio}
              onPlayingAudioChange={setPlayingAudio}
              onPlayAudio={handlePlayAudio}
              onDeleteAudio={handleDeleteAudio}
              audioFileUrl={api.getAudioFileUrl}
              voiceWorkstationStatus={voiceWorkstationStatus}
              audioConfig={audioConfig}
              onAudioConfigChange={setAudioConfig}
              speedMax={speedMax}
              vadConfig={vadConfig}
              onVadConfigChange={setVadConfig}
              sensevoiceStreamingConfig={sensevoiceStreamingConfig}
              onSensevoiceStreamingConfigChange={setSensevoiceStreamingConfig}
              adaptivePollingConfig={adaptivePollingConfig}
              onAdaptivePollingConfigChange={setAdaptivePollingConfig}
              adaptivePollingStats={adaptivePollingStats}
              firewallV3Config={firewallV3Config}
              onFirewallV3ConfigChange={setFirewallV3Config}
              onSave={handleSave}
              saveStatus={saveStatus}
            />
          )}

          {activeSection === 'live2d' && (
            <Live2DCard
              showAvatarManager={showAvatarManager}
              onShowAvatarManagerChange={setShowAvatarManager}
              speedMax={speedMax}
              onSpeedMaxChange={setSpeedMax}
              avatarType={avatarType}
              onAvatarTypeChange={setAvatarType}
              limits={limits}
              onSave={handleSave}
              saveStatus={saveStatus}
            />
          )}

          {activeSection === 'live' && (
            <LiveCard
              liveClientStatus={liveClientStatus}
              newBlacklistUid={newBlacklistUid}
              onNewBlacklistUidChange={setNewBlacklistUid}
              firewallConfig={firewallConfig}
              onFirewallConfigChange={setFirewallConfig}
              danmakuConfig={danmakuConfig}
              onDanmakuConfigChange={setDanmakuConfig}
              onDisconnectLive={handleDisconnectLive}
              onSave={handleSave}
              saveStatus={saveStatus}
            />
          )}
        </div>
      </div>

      {showAvatarManager && (
        <AvatarManager
          type={showAvatarManager}
          onClose={() => setShowAvatarManager(null)}
        />
      )}
    </div>
  );
}
