import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { cn } from '../lib/utils';
import { useThemeStore } from '../store/themeStore';
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
  const [activeSection, setActiveSection] = useState<'appearance' | 'service' | 'audio' | 'live' | 'vector' | 'graph' | 'llm'>(
    'appearance'
  );
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [logs, setLogs] = useState('');
  const [isBackendRunning, setIsBackendRunning] = useState(false);
  const [isControlServiceReady, setIsControlServiceReady] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [backendStatus, setBackendStatus] = useState<{
    pid?: number;
    uptime?: number;
    port?: number;
  }>({});
  const [themeTransition, setThemeTransition] = useState(false);

  const { theme, setTheme } = useThemeStore();
  const [selectedAccent, setSelectedAccent] = useState('#3b82f6');

  const handleThemeChange = (newTheme: 'light' | 'dark' | 'system') => {
    setThemeTransition(true);
    setTheme(newTheme);
    setTimeout(() => setThemeTransition(false), 300);
  };

  const checkControlService = useCallback(async () => {
    try {
      const controlUrl = import.meta.env.VITE_CONTROL_SERVICE_URL || 'http://localhost:8765';
      const response = await fetch(`${controlUrl}/health`);
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
    cxhms: { url: 'ws://127.0.0.1:8000/ws', http_url: 'http://127.0.0.1:8000', timeout: 30 },
    asr: { url: 'http://127.0.0.1:8001', timeout: 60 },
    tts: { url: 'http://127.0.0.1:8002', timeout: 120 },
    index_tts: { url: 'http://127.0.0.1:8004', enabled: true, timeout: 180 },
  });
  const [isGatewayConfigLoading, setIsGatewayConfigLoading] = useState(false);

  useEffect(() => {
    const loadGatewayConfig = async () => {
      if (!isBackendRunning) return;
      try {
        const data = await api.getServiceConfig();
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
    setIsGatewayConfigLoading(true);
    try {
      const result = await api.updateServiceConfig(gatewayServicesConfig);
      if (result.status === 'success') {
        alert('Gateway 服务配置已保存，需要重启服务生效');
      } else {
        alert('保存失败: ' + result.message);
      }
    } catch (error) {
      console.error('Failed to update Gateway config:', error);
      alert('保存失败');
    } finally {
      setIsGatewayConfigLoading(false);
    }
  };

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
  const [indexTtsStatus, setIndexTtsStatus] = useState<{ status: string; message?: string; url?: string } | null>(null);
  const [generatingEmotions, setGeneratingEmotions] = useState(false);
  const [generateProgress, setGenerateProgress] = useState<{ current: number; total: number; emotion: string } | null>(null);

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

  const [testingConnection, setTestingConnection] = useState(false);

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
        const data = await api.getAudioConfig();
        if (data.config) {
          setAudioConfig({
            ref_audio_path: data.config.ref_audio_path || '',
            ref_text: data.config.ref_text || '',
            speed: data.config.speed || 1.0,
            cross_fade_duration: data.config.cross_fade_duration || 0.15,
            emotion_enabled: data.config.emotion_enabled ?? true,
            effects_enabled: data.config.effects_enabled ?? true,
            emotion_voices: data.config.emotion_voices || [],
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
        const data = await api.getAudioFiles();
        if (data.status === 'success') {
          setAudioFiles(data.files || []);
        }
      } catch (error) {
        console.error('Failed to load audio files:', error);
      }
    };
    loadAudioFiles();
  }, []);

  useEffect(() => {
    const checkIndexTTSStatus = async () => {
      try {
        const data = await api.getIndexTTSStatus();
        setIndexTtsStatus(data);
      } catch (error) {
        console.error('Failed to check IndexTTS status:', error);
        setIndexTtsStatus({ status: 'error', message: '无法连接服务' });
      }
    };
    checkIndexTTSStatus();
    const interval = setInterval(checkIndexTTSStatus, 30000);
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
        ]);

        if (danmakuData.config) {
          setDanmakuConfig(danmakuData.config);
        }
        if (firewallData.config) {
          setFirewallConfig(firewallData.config);
        }
        if (firewallV3Data.config) {
          setFirewallV3Config(firewallV3Data.config);
        }
        if (liveStatus) {
          setLiveClientStatus(liveStatus);
        }
        if (vadData.config) {
          setVadConfig(vadData.config);
        }
        if (sensevoiceData.config) {
          setSensevoiceStreamingConfig({
            chunk_size: sensevoiceData.config.chunk_size ?? 1600,
            hop_size: sensevoiceData.config.hop_size ?? 800,
            look_back: sensevoiceData.config.look_back ?? 8000,
          });
        }
        if (adaptivePollingData.config) {
          setAdaptivePollingConfig({
            offset_ms: adaptivePollingData.config.offset_ms ?? 0,
            window_size: adaptivePollingData.config.window_size ?? 3,
          });
        }
        if (adaptivePollingData.stats) {
          setAdaptivePollingStats(adaptivePollingData.stats);
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
        ]);

        if (configData.status === 'success' && configData.config) {
          setGraphConfig({
            graph_enabled: configData.config.graph_enabled ?? false,
            graph_backend: configData.config.graph_backend ?? 'neo4j',
            neo4j: configData.config.neo4j ?? graphConfig.neo4j,
            graph_libraries: configData.config.graph_libraries ?? graphConfig.graph_libraries,
          });
        }
        if (healthData) {
          setGraphHealth(healthData);
        }
        if (statsData.status === 'success' && statsData.graph_status) {
          setGraphStats(statsData.graph_status);
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
      if (result.status === 'success') {
        setAudioFiles((prev) => [
          ...prev,
          { name: result.filename, size: file.size, modified: Date.now() },
        ]);
      } else {
        alert(result.message || '上传失败');
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

  const handleGenerateEmotions = async () => {
    if (!audioConfig.ref_audio_path) {
      alert('请先选择参考音频');
      return;
    }

    setGeneratingEmotions(true);
    setGenerateProgress({ current: 0, total: 5, emotion: '' });

    try {
      const emotions = [
        { type: 'happy', intensity: 1.0 },
        { type: 'sad', intensity: 1.0 },
        { type: 'angry', intensity: 1.0 },
        { type: 'surprised', intensity: 1.0 },
        { type: 'tender', intensity: 1.0 },
      ];

      const result = await api.generateEmotionAudios({
        ref_audio: audioConfig.ref_audio_path,
        ref_text: audioConfig.ref_text,
        emotions,
        template: 'full',
        auto_full: true,
      });

      const filesData = await api.getAudioFiles();
      if (filesData.status === 'success') {
        setAudioFiles(filesData.files || []);
      }

      const configData = await api.getAudioConfig();
      if (configData.config) {
        setAudioConfig((prev) => ({
          ...prev,
          emotion_voices: configData.config.emotion_voices || prev.emotion_voices,
        }));
      }

      const status = await api.getIndexTTSStatus();
      setIndexTtsStatus(status);

      if (result.errors && Object.keys(result.errors).length > 0) {
        alert(`部分情感生成失败：${Object.keys(result.errors).join(', ')}`);
      } else if (result.generated) {
        alert(`成功生成 ${Object.keys(result.generated).length} 个情感音频！`);
      } else {
        alert('情感音频生成完成！');
      }
    } catch (error) {
      console.error('Generate emotions error:', error);
      alert('生成失败');
    } finally {
      setGeneratingEmotions(false);
      setGenerateProgress(null);
    }
  };

  useEffect(() => {
    if (serviceConfig?.config) {
      if (serviceConfig.config.vector) {
        const vec = serviceConfig.config.vector;
        setVectorConfig({
          backend: vec.backend ?? vec.vector_backend ?? 'weaviate',
          vectorSize: vec.vector_size ?? 768,
          dbPath: vec.db_path ?? 'data/chroma_db',
          collectionName: vec.collection_name ?? 'memory_vectors',
          weaviateHost: vec.host ?? vec.weaviate_host ?? 'localhost',
          weaviatePort: vec.port ?? vec.weaviate_port ?? 8090,
          qdrantHost: vec.qdrant_host ?? 'localhost',
          qdrantPort: vec.qdrant_port ?? 6333,
        });
      }
      if (serviceConfig.config.models) {
        setModelsConfig((prev) => ({
          main: serviceConfig.config.models?.main
            ? { ...prev.main, ...serviceConfig.config.models.main }
            : prev.main,
          summary: serviceConfig.config.models?.summary
            ? { ...prev.summary, ...serviceConfig.config.models.summary }
            : prev.summary,
          memory: serviceConfig.config.models?.memory
            ? { ...prev.memory, ...serviceConfig.config.models.memory }
            : prev.memory,
        }));
      }
      if (serviceConfig.config.llm_params) {
        setLlmParams({
          temperature: serviceConfig.config.llm_params.temperature ?? 0.7,
          maxTokens: serviceConfig.config.llm_params.maxTokens ?? 2048,
          topP: serviceConfig.config.llm_params.topP ?? 0.9,
          timeout: serviceConfig.config.llm_params.timeout ?? 30,
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
      const response = await fetch('http://localhost:8000/health');
      if (response.ok) {
        alert('后端服务已在运行');
        setIsBackendRunning(true);
      } else {
        alert('请手动启动后端服务: cd CXHMS && python main.py');
      }
    } catch {
      alert('请手动启动后端服务: cd CXHMS && python main.py');
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
          await api.updateConfig({ section: 'audio', data: audioConfig });
          break;
        case 'live':
          await api.updateConfig({
            section: 'live',
            data: {
              danmaku: danmakuConfig,
              firewall: firewallConfig,
              firewall_v3: firewallV3Config,
              vad: vadConfig,
              sensevoice_streaming: sensevoiceStreamingConfig,
              adaptive_polling: adaptivePollingConfig,
            },
          });
          break;
        case 'vector':
          await api.updateConfig({ section: 'vector', data: vectorConfig });
          break;
        case 'graph':
          await api.updateConfig({ section: 'graph', data: graphConfig });
          break;
        case 'llm': {
          const updatedModelDefaults = {
            summary: modelsConfig.summary.enabled ? 'summary' : 'main',
            memory: modelsConfig.memory.enabled ? 'memory' : 'main',
          };
          await api.updateLLMConfig({
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
    setTimeout(() => setSaveStatus('idle'), 2000);
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
                      <h3 className="text-lg font-semibold">Gateway 服务配置</h3>
                      <p className="text-sm text-[var(--color-text-secondary)]">
                        管理各微服务连接 (ASR/TTS/Index-TTS)
                      </p>
                    </div>
                    <Button
                      onClick={handleUpdateGatewayServices}
                      loading={isGatewayConfigLoading}
                    >
                      保存配置
                    </Button>
                  </div>

                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">CXHMS 后端 URL</label>
                        <input
                          type="text"
                          value={gatewayServicesConfig.cxhms.url}
                          onChange={(e) => setGatewayServicesConfig({
                            ...gatewayServicesConfig,
                            cxhms: { ...gatewayServicesConfig.cxhms, url: e.target.value }
                          })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="ws://127.0.0.1:8000/ws"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">CXHMS HTTP URL</label>
                        <input
                          type="text"
                          value={gatewayServicesConfig.cxhms.http_url || ''}
                          onChange={(e) => setGatewayServicesConfig({
                            ...gatewayServicesConfig,
                            cxhms: { ...gatewayServicesConfig.cxhms, http_url: e.target.value }
                          })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="http://127.0.0.1:8000"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">ASR 服务 URL</label>
                        <input
                          type="text"
                          value={gatewayServicesConfig.asr.url}
                          onChange={(e) => setGatewayServicesConfig({
                            ...gatewayServicesConfig,
                            asr: { ...gatewayServicesConfig.asr, url: e.target.value }
                          })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="http://127.0.0.1:8001"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">ASR 超时 (秒)</label>
                        <input
                          type="number"
                          value={gatewayServicesConfig.asr.timeout}
                          onChange={(e) => setGatewayServicesConfig({
                            ...gatewayServicesConfig,
                            asr: { ...gatewayServicesConfig.asr, timeout: parseInt(e.target.value) || 60 }
                          })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">TTS 服务 URL</label>
                        <input
                          type="text"
                          value={gatewayServicesConfig.tts.url}
                          onChange={(e) => setGatewayServicesConfig({
                            ...gatewayServicesConfig,
                            tts: { ...gatewayServicesConfig.tts, url: e.target.value }
                          })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="http://127.0.0.1:8002"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">TTS 超时 (秒)</label>
                        <input
                          type="number"
                          value={gatewayServicesConfig.tts.timeout}
                          onChange={(e) => setGatewayServicesConfig({
                            ...gatewayServicesConfig,
                            tts: { ...gatewayServicesConfig.tts, timeout: parseInt(e.target.value) || 120 }
                          })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <label className="text-sm font-medium mb-2 block">Index-TTS URL</label>
                        <input
                          type="text"
                          value={gatewayServicesConfig.index_tts.url}
                          onChange={(e) => setGatewayServicesConfig({
                            ...gatewayServicesConfig,
                            index_tts: { ...gatewayServicesConfig.index_tts, url: e.target.value }
                          })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="http://127.0.0.1:8004"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">Index-TTS 超时 (秒)</label>
                        <input
                          type="number"
                          value={gatewayServicesConfig.index_tts.timeout}
                          onChange={(e) => setGatewayServicesConfig({
                            ...gatewayServicesConfig,
                            index_tts: { ...gatewayServicesConfig.index_tts, timeout: parseInt(e.target.value) || 180 }
                          })}
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium mb-2 block">启用 Index-TTS</label>
                        <label className="flex items-center gap-2 mt-2">
                          <input
                            type="checkbox"
                            checked={gatewayServicesConfig.index_tts.enabled}
                            onChange={(e) => setGatewayServicesConfig({
                              ...gatewayServicesConfig,
                              index_tts: { ...gatewayServicesConfig.index_tts, enabled: e.target.checked }
                            })}
                            className="w-4 h-4"
                          />
                          <span>启用</span>
                        </label>
                      </div>
                    </div>
                  </div>
                </CardBody>
              </Card>

              <Card>
                <CardBody>
                  <div className="flex items-center justify-between mb-6">
                    <div>
                      <h3 className="text-lg font-semibold">CXHMS 后端服务</h3>
                      <p className="text-sm text-[var(--color-text-secondary)]">
                        管理 CXHMS 后端服务
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
                      <p className="font-medium">{backendStatus.port || 8000}</p>
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
                          <div className="text-lg font-semibold">{graphStats?.node_count || 0}</div>
                          <div className="text-xs text-[var(--color-text-tertiary)]">节点</div>
                        </div>
                        <div className="text-center">
                          <div className="text-lg font-semibold">{graphStats?.edge_count || 0}</div>
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
                        variant="outline"
                        onClick={async () => {
                          try {
                            const result = await api.getGraphStats();
                            setGraphStats(result);
                          } catch {
                            console.error('获取图统计失败');
                          }
                        }}
                      >
                        刷新统计
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={async () => {
                          try {
                            const health = await api.getGraphHealth();
                            setGraphHealth(health);
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

              {/* CosyVoice 情感音频生成 */}
              <Card>
                <CardBody>
                  <h3 className="text-lg font-semibold mb-4">情感音频生成</h3>
                  <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                    使用 IndexTTS 2 从一条参考音频自动生成所有情感的参考音频
                  </p>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
                      <div className="flex items-center gap-3">
                        <span
                          className={`w-3 h-3 rounded-full ${
                            indexTtsStatus?.status === 'running'
                              ? 'bg-green-500'
                              : indexTtsStatus?.status === 'starting'
                              ? 'bg-yellow-500 animate-pulse'
                              : indexTtsStatus?.status === 'disabled'
                              ? 'bg-gray-400'
                              : 'bg-red-500'
                          }`}
                        />
                        <div>
                          <div className="text-sm font-medium">IndexTTS 2 服务</div>
                          <div className="text-xs text-[var(--color-text-tertiary)]">
                            {indexTtsStatus?.status === 'running'
                              ? `运行中 - ${indexTtsStatus.url}`
                              : indexTtsStatus?.status === 'starting'
                              ? '启动中...'
                              : indexTtsStatus?.status === 'disabled'
                              ? '已禁用'
                              : '已停止'}
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-4">
                      <button
                        onClick={handleGenerateEmotions}
                        disabled={
                          generatingEmotions ||
                          !audioConfig.ref_audio_path ||
                          indexTtsStatus?.status === 'starting'
                        }
                        className={`flex items-center gap-2 px-4 py-2 rounded-[var(--radius-md)] transition-colors ${
                          generatingEmotions ||
                          !audioConfig.ref_audio_path ||
                          indexTtsStatus?.status === 'starting'
                            ? 'bg-[var(--color-border)] text-[var(--color-text-tertiary)] cursor-not-allowed'
                            : 'bg-[var(--color-accent)] text-white hover:opacity-90'
                        }`}
                      >
                        <svg
                          className="w-5 h-5"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M13 10V3L4 14h7v7l9-11h-7z"
                          />
                        </svg>
                        <span>
                          {generatingEmotions
                            ? `生成中... ${generateProgress?.current || 0}/${generateProgress?.total || 5}`
                            : '生成情感音频'}
                        </span>
                      </button>
                      <span className="text-sm text-[var(--color-text-tertiary)]">
                        将为 happy, sad, angry, surprised, tender 生成情感音频
                      </span>
                    </div>

                    {!audioConfig.ref_audio_path && (
                      <p className="text-sm text-amber-600">
                        请先在上方 TTS 基础配置中选择参考音频
                      </p>
                    )}
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
