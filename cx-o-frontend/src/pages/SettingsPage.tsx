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
    description: 'TTS 参考音频和情感语音配置',
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
  const [activeSection, setActiveSection] = useState<'appearance' | 'service' | 'audio' | 'vector' | 'llm'>(
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
      await api.getControlServiceHealth();
      setIsControlServiceReady(true);
      return true;
    } catch {
      setIsControlServiceReady(false);
      return false;
    }
  }, []);

  const checkBackendStatus = useCallback(async () => {
    try {
      const status = await api.getMainBackendStatus();
      setIsBackendRunning(status.running);
      setBackendStatus({
        pid: status.pid,
        uptime: status.uptime,
        port: status.port,
      });
      return status.running;
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

  const [vectorConfig, setVectorConfig] = useState({
    backend: 'chroma',
    vectorSize: 768,
    dbPath: 'data/chroma_db',
    collectionName: 'memory_vectors',
    weaviateHost: 'localhost',
    weaviatePort: 8080,
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
          backend: vec.backend ?? 'chroma',
          vectorSize: vec.vector_size ?? 768,
          dbPath: vec.db_path ?? 'data/chroma_db',
          collectionName: vec.collection_name ?? 'memory_vectors',
          weaviateHost: vec.weaviate_host ?? 'localhost',
          weaviatePort: vec.weaviate_port ?? 8080,
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
    if (!isControlServiceReady) {
      alert('控制服务未就绪，请稍后再试');
      return;
    }
    setIsProcessing(true);
    try {
      await api.startMainBackend();
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await checkBackendStatus();
    } catch {
      alert('启动后端服务失败，请检查控制台日志');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleStopBackend = async () => {
    if (!isControlServiceReady) {
      alert('控制服务未就绪');
      return;
    }
    setIsProcessing(true);
    try {
      await api.stopMainBackend();
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await checkBackendStatus();
    } catch {
      alert('停止后端服务失败');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleRestartBackend = async () => {
    if (!isControlServiceReady) {
      alert('控制服务未就绪');
      return;
    }
    setIsProcessing(true);
    try {
      await api.restartMainBackend();
      await new Promise((resolve) => setTimeout(resolve, 3000));
      await checkBackendStatus();
    } catch {
      alert('重启后端服务失败');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleSave = async () => {
    setSaveStatus('saving');
    try {
      if (activeSection === 'vector') {
        if (!isBackendRunning) {
          alert('后端服务未运行，无法保存配置');
          return;
        }
        const vectorPayload: Record<string, unknown> = {
          backend: vectorConfig.backend,
          vector_size: vectorConfig.vectorSize,
        };

        if (vectorConfig.backend === 'chroma') {
          vectorPayload.db_path = vectorConfig.dbPath;
          vectorPayload.collection_name = vectorConfig.collectionName;
        } else if (vectorConfig.backend === 'milvus_lite') {
          vectorPayload.db_path = vectorConfig.dbPath;
        } else if (
          vectorConfig.backend === 'weaviate' ||
          vectorConfig.backend === 'weaviate_embedded'
        ) {
          vectorPayload.weaviate_host = vectorConfig.weaviateHost;
          vectorPayload.weaviate_port = vectorConfig.weaviatePort;
        } else if (vectorConfig.backend === 'qdrant') {
          vectorPayload.qdrant_host = vectorConfig.qdrantHost;
          vectorPayload.qdrant_port = vectorConfig.qdrantPort;
        }

        await api.updateServiceConfig({
          vector: vectorPayload,
        });
      } else if (activeSection === 'llm') {
        if (!isBackendRunning) {
          alert('后端服务未运行，无法保存配置');
          return;
        }
        const updatedModelDefaults = {
          summary: modelsConfig.summary.enabled ? 'summary' : 'main',
          memory: modelsConfig.memory.enabled ? 'memory' : 'main',
        };
        await api.updateServiceConfig({
          models: modelsConfig,
          model_defaults: updatedModelDefaults,
          llm_params: llmParams,
        });
        localStorage.setItem('cxhms-current-model', modelsConfig.main.model);
      } else if (activeSection === 'audio') {
        await api.updateAudioConfig(audioConfig);
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
                      <h3 className="text-lg font-semibold">服务管理</h3>
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
                          disabled={!isControlServiceReady}
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
                        <option value="chroma">Chroma (推荐 Windows)</option>
                        <option value="milvus_lite">Milvus Lite (仅 Linux/macOS)</option>
                        <option value="weaviate_embedded">Weaviate Embedded</option>
                        <option value="weaviate">Weaviate (独立服务)</option>
                        <option value="qdrant">Qdrant</option>
                      </select>
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
                    {vectorConfig.backend === 'chroma' && (
                      <div>
                        <label className="text-sm font-medium mb-2 block">数据存储路径</label>
                        <input
                          type="text"
                          value={vectorConfig.dbPath || 'data/chroma_db'}
                          onChange={(e) =>
                            setVectorConfig({ ...vectorConfig, dbPath: e.target.value })
                          }
                          className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                          placeholder="data/chroma_db"
                        />
                      </div>
                    )}
                    {(vectorConfig.backend === 'weaviate' ||
                      vectorConfig.backend === 'weaviate_embedded') && (
                      <>
                        <div>
                          <label className="text-sm font-medium mb-2 block">Weaviate 主机</label>
                          <input
                            type="text"
                            value={vectorConfig.weaviateHost || 'localhost'}
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
                            value={vectorConfig.weaviatePort || 8080}
                            onChange={(e) =>
                              setVectorConfig({
                                ...vectorConfig,
                                weaviatePort: parseInt(e.target.value),
                              })
                            }
                            className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                            placeholder="8080"
                          />
                        </div>
                      </>
                    )}
                    {vectorConfig.backend === 'qdrant' && (
                      <>
                        <div>
                          <label className="text-sm font-medium mb-2 block">Qdrant 主机</label>
                          <input
                            type="text"
                            value={vectorConfig.qdrantHost || 'localhost'}
                            onChange={(e) =>
                              setVectorConfig({ ...vectorConfig, qdrantHost: e.target.value })
                            }
                            className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                            placeholder="localhost"
                          />
                        </div>
                        <div>
                          <label className="text-sm font-medium mb-2 block">Qdrant 端口</label>
                          <input
                            type="number"
                            value={vectorConfig.qdrantPort || 6333}
                            onChange={(e) =>
                              setVectorConfig({
                                ...vectorConfig,
                                qdrantPort: parseInt(e.target.value),
                              })
                            }
                            className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                            placeholder="6333"
                          />
                        </div>
                      </>
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
                  <div className="flex justify-end mt-6">
                    <Button onClick={handleSave} loading={saveStatus === 'saving'}>
                      {saveStatus === 'saved' ? '已保存' : '保存配置'}
                    </Button>
                  </div>
                </CardBody>
              </Card>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
