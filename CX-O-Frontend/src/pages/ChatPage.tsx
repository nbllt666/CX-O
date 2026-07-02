import { useState, useRef, useEffect, useCallback } from 'react';
import { api } from '../api/client';
import { useChatStore } from '../store/chatStore';
import { useSettingsStore } from '../store/settingsStore';
import { SummaryModal } from '../components/SummaryModal';
import { useWebSocket } from '../hooks/useWebSocket';
import { useAudioStream } from '../hooks/useAudioStream';
import { AvatarPanel } from '../components/Avatar';
import type { IAvatarDriver } from '../components/Avatar/AvatarDriver';
import { createAvatarDriver } from '../components/Avatar/AvatarDriver';
import { resolveAvatarManifestById, getAvatarById } from '../components/Avatar/avatarManifest';
import { parseAvatarTags } from '../lib/avatarTagParser';
import { applyAvatarTags, playTTSWithPauses } from './chat/utils';
import type { Message, ToolCall, StreamToolCall } from './chat/types';
import { ChatToolbar } from './chat/ChatToolbar';
import { DualStreamStatusBar } from './chat/DualStreamStatusBar';
import { MessageList } from './chat/MessageList';
import { ChatInput } from './chat/ChatInput';
import { AlarmNotifications } from './chat/AlarmNotifications';

export function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showSummaryModal, setShowSummaryModal] = useState(false);
  const [autoStartSummary, setAutoStartSummary] = useState(false);
  const [selectedImages, setSelectedImages] = useState<string[]>([]);
  const [alarms, setAlarms] = useState<{ message: string; triggeredAt: string }[]>([]);
  const [maxChatImages, setMaxChatImages] = useState(20);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const tempAssistantIdRef = useRef<string>('');
  const lastDoneContentRef = useRef<string | null>(null);
  const alarmTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const loadHistoryCancelledRef = useRef<{ cancelled: boolean }>({ cancelled: false });
  const [doneTrigger, setDoneTrigger] = useState(0);

  const [isRecording, setIsRecording] = useState(false);
  const [isVoiceMode, setIsVoiceMode] = useState(false);
  const [enableVoiceOutput, setEnableVoiceOutput] = useState(false);
  const [currentAudioElement, setCurrentAudioElement] = useState<HTMLAudioElement | null>(null);
  const [isAudioPlaying, setIsAudioPlaying] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const playAudioRef = useRef<(audioData: ArrayBuffer, isLastSegment?: boolean) => Promise<void>>();

  // ========== 双流式实时语音模式状态 ==========
  // 双流式：ASR Partial 主驱动，TTS 边收边播，全双工可打断
  const [isDualStreamMode, setIsDualStreamMode] = useState(false);
  // 用户实时识别字幕（interim subtitle），随 Partial 修正更新
  const [partialSubtitle, setPartialSubtitle] = useState('');
  // LLM Prefill 已启动、等待首个 TTS 音频块的"正在思考"状态
  const [dualThinking, setDualThinking] = useState(false);
  // 当前双流式 assistant 消息 id（用于流式追加 text_segment）
  const dualAssistantIdRef = useRef<string>('');
  // TTS 播放状态 ref：供 barge-in 回调读取最新值，避免闭包捕获过期 state
  const isTTSPlayingRef = useRef(false);
  // 双流式 TTS 引擎选择：f5-tts（默认，向后兼容）或 orpheus
  const [dualStreamEngine, setDualStreamEngine] = useState<'f5-tts' | 'orpheus'>('f5-tts');
  // Orpheus 音色名（仅 orpheus 引擎使用），默认 tara
  const [orpheusVoice, setOrpheusVoice] = useState<string>('tara');

  const driverRef = useRef<IAvatarDriver | null>(null);
  const [activeDriver, setActiveDriver] = useState<IAvatarDriver | null>(null);

  // 虚拟形象和布局状态
  const { layout, toggleChatCollapsed, limits } = useSettingsStore();
  const { avatarType, live2d, vrm } = useSettingsStore();

  const { agents, currentAgentId, fetchAgents } = useChatStore();

  useEffect(() => {
    let cancelled = false;
    const avatarId = avatarType === 'live2d' ? (live2d.modelId || 'yumi') : (vrm.modelId || undefined);
    const baseAvatar = avatarId ? getAvatarById(avatarId) : undefined;
    if (!baseAvatar) {
      driverRef.current = null;
      setActiveDriver(null);
      return;
    }
    resolveAvatarManifestById(baseAvatar.id)
      .then((manifest) => {
        if (cancelled) return;
        const driver = createAvatarDriver(manifest);
        driverRef.current = driver;
        setActiveDriver(driver);
      })
      .catch(() => {
        if (cancelled) return;
        const driver = createAvatarDriver(baseAvatar);
        driverRef.current = driver;
        setActiveDriver(driver);
      });
    return () => { cancelled = true; };
  }, [avatarType, live2d.modelId, vrm.modelId]);

  const handleWebSocketMessage = useCallback(
    (data: {
      type: string;
      content?: string;
      done?: boolean;
      error?: string | { code: string; message: string };
      tool_call?: Record<string, unknown>;
      tool_name?: string;
      result?: unknown;
      thinking?: string;
      data?: Record<string, unknown>;
    }) => {
      if (data.type === 'external_event') {
        const eventData = data.data || {};
        setMessages(prev => [...prev, {
          id: `ext-${Date.now()}`,
          role: 'system' as const,
          content: `[外部事件] ${eventData.source || '未知来源'}: ${eventData.title || eventData.body || ''}`,
          timestamp: new Date().toISOString(),
          type: 'external_event',
          eventData: eventData,
        }]);
        return;
      }

      if (data.type === 'content' && data.content) {
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.id === tempAssistantIdRef.current) {
            return [
              ...prev.slice(0, -1),
              {
                ...lastMsg,
                content: lastMsg.content + data.content!,
              },
            ];
          }
          return prev;
        });
      } else if (data.type === 'tool_call' && data.tool_call) {
        const tc = data.tool_call as StreamToolCall;
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.id === tempAssistantIdRef.current) {
            return [
              ...prev.slice(0, -1),
              {
                ...lastMsg,
                tool_calls: [
                  ...(lastMsg.tool_calls || []),
                  {
                    id: tc.id || Date.now().toString(),
                    name: tc.name || tc.function?.name || 'unknown',
                    arguments: tc.arguments || tc.function?.arguments,
                    status: 'pending',
                  },
                ],
              },
            ];
          }
          return prev;
        });
      } else if (data.type === 'tool_start' && data.tool_name) {
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.id === tempAssistantIdRef.current && lastMsg.tool_calls) {
            return [
              ...prev.slice(0, -1),
              {
                ...lastMsg,
                tool_calls: lastMsg.tool_calls.map((tc) =>
                  tc.name === data.tool_name ? { ...tc, status: 'executing' } : tc
                ),
              },
            ];
          }
          return prev;
        });
      } else if (data.type === 'tool_result' && data.tool_name && data.result !== undefined) {
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.id === tempAssistantIdRef.current && lastMsg.tool_calls) {
            const updatedToolCalls: ToolCall[] = lastMsg.tool_calls.map((tc) =>
              tc.name === data.tool_name
                ? { ...tc, status: 'completed' as const, result: data.result }
                : tc
            );
            return [
              ...prev.slice(0, -1),
              {
                ...lastMsg,
                tool_calls: updatedToolCalls,
              },
            ];
          }
          return prev;
        });
      } else if (data.type === 'thinking' && data.content) {
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.id === tempAssistantIdRef.current) {
            return [
              ...prev.slice(0, -1),
              {
                ...lastMsg,
                thinking: (lastMsg.thinking || '') + data.content,
              },
            ];
          }
          return prev;
        });
      } else if (data.type === 'done') {
        setIsLoading(false);
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.id === tempAssistantIdRef.current) {
            const finalContent = lastMsg.content || '响应已完成';
            lastDoneContentRef.current = finalContent;
            return [
              ...prev.slice(0, -1),
              {
                ...lastMsg,
                content: finalContent,
              },
            ];
          }
          return prev;
        });
        setDoneTrigger(t => t + 1);
      } else if (data.type === 'error') {
        setIsLoading(false);
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.id === tempAssistantIdRef.current) {
            return [
              ...prev.slice(0, -1),
              {
                ...lastMsg,
                content: `抱歉，发生错误：${data.error || '未知错误'}`,
              },
            ];
          }
          return prev;
        });
      } else if (data.type === 'cancelled') {
        setIsLoading(false);
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.id === tempAssistantIdRef.current) {
            return [
              ...prev.slice(0, -1),
              {
                ...lastMsg,
                content: lastMsg.content || '响应已取消',
              },
            ];
          }
          return prev;
        });
      }
    },
    [],
  );

  useEffect(() => {
    const content = lastDoneContentRef.current;
    if (content === null) return;
    lastDoneContentRef.current = null;

    setIsLoading(false);
    const { segments, cleanText, tags } = parseAvatarTags(content);
    const driver = driverRef.current;
    if (driver) {
      applyAvatarTags(driver, tags);
    }
    if (enableVoiceOutput && cleanText) {
      const hasSleepTag = segments.some(s => s.type === 'tag' && s.tag.type === 'sleep');
      if (hasSleepTag) {
        playTTSWithPauses(
          segments,
          (text) => api.textToSpeech(text),
          (audioData, isLast) => playAudioRef.current?.(audioData, isLast) ?? Promise.resolve(),
        );
      } else {
        api.textToSpeech(cleanText).then((audioBlob: Blob) => {
          return audioBlob.arrayBuffer().then((arrayBuffer: ArrayBuffer) => {
            playAudioRef.current?.(arrayBuffer);
          });
        }).catch((error: Error) => {
          console.error('TTS failed:', error);
        });
      }
    }
    if (cleanText !== content) {
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1];
        if (lastMsg && lastMsg.id === tempAssistantIdRef.current) {
          return [
            ...prev.slice(0, -1),
            { ...lastMsg, content: cleanText },
          ];
        }
        return prev;
      });
    }
  }, [doneTrigger, enableVoiceOutput]);

  const handleAlarm = useCallback((message: string, triggeredAt: string) => {
    setAlarms((prev) => [...prev, { message, triggeredAt }]);
    if (alarmTimeoutRef.current) {
      clearTimeout(alarmTimeoutRef.current);
    }
    alarmTimeoutRef.current = setTimeout(() => {
      setAlarms((prev) => prev.slice(1));
      alarmTimeoutRef.current = null;
    }, 5000);
  }, []);

  // ========== 双流式回调 ==========
  // 通过 ref 读取 useWebSocket 返回的 interruptTTS，打破"回调定义在 useWebSocket 之前"的循环依赖
  const interruptTTSRef = useRef<() => void>(() => {});

  // ASR Partial：实时更新用户字幕；同时作为全双工打断触发点
  const handleDualPartial = useCallback((text: string) => {
    // 全双工打断（SubTask 6.4）：用户开口（Partial 到来）且 TTS 正在播放时，
    // 立即停止播放、清空队列。省去等待整句播放完毕的延迟，实现毫秒级 barge-in。
    if (isTTSPlayingRef.current) {
      interruptTTSRef.current();
      setDualThinking(false);
    }
    setPartialSubtitle(text);
  }, []);

  // LLM Prefill 已启动：用户文本已确认，落为 user 消息，清空 interim 字幕
  const handleDualPrefillStarted = useCallback((text: string) => {
    setPartialSubtitle('');
    setDualThinking(true);
    const userMsgId = `dual-user-${Date.now()}`;
    const assistantMsgId = `dual-asst-${Date.now() + 1}`;
    dualAssistantIdRef.current = assistantMsgId;
    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user' as const, content: text, timestamp: new Date().toISOString() },
      { id: assistantMsgId, role: 'assistant' as const, content: '', timestamp: new Date().toISOString() },
    ]);
    setShouldAutoScroll(true);
  }, []);

  // TTS 音频块：音频由 useWebSocket 内部队列自动播放，这里只负责累积助手文本用于显示
  const handleDualTTSChunk = useCallback((_audio: string, _isFinal: boolean, textSegment?: string) => {
    setDualThinking(false);
    if (textSegment) {
      const seg = textSegment;
      setMessages(prev => {
        const id = dualAssistantIdRef.current;
        const idx = prev.findIndex(m => m.id === id);
        if (idx === -1) return prev;
        const updated = [...prev];
        updated[idx] = { ...updated[idx], content: (updated[idx].content || '') + seg };
        return updated;
      });
    }
  }, []);

  // TTS 播放状态变化：同步 ref（供 barge-in 读取）+ 口型同步
  const handleTTSPlayingChange = useCallback((playing: boolean) => {
    isTTSPlayingRef.current = playing;
    // 双流式 TTS 经 AudioContext 播放，不走 HTMLAudioElement，
    // 故 AvatarPanel 的口型同步失效，这里直接驱动口型
    driverRef.current?.setMouthOpen(playing ? 0.6 : 0);
  }, []);

  const {
    isConnected,
    sendMessage: wsSendMessage,
    cancelGeneration,
    isTTSPlaying,
    interruptTTS,
    sendRaw,
  } = useWebSocket({
    agentId: currentAgentId || '',
    timeout: 60,
    onMessage: handleWebSocketMessage,
    onAlarm: handleAlarm,
    onError: (error) => {
      console.error('WebSocket error:', error);
      setIsLoading(false);
    },
    onPartial: handleDualPartial,
    onTTSChunk: handleDualTTSChunk,
    onPrefillStarted: handleDualPrefillStarted,
    onTTSPlayingChange: handleTTSPlayingChange,
  });

  // 将 interruptTTS 注入 ref，供 handleDualPartial 在 barge-in 时调用
  useEffect(() => {
    interruptTTSRef.current = interruptTTS;
  }, [interruptTTS]);

  // 双流式音频采集 hook：持续推送音频流（不等 VAD on_end），通过 sendRaw 复用同一 WS 连接
  const {
    isDualStreaming,
    startDualStream,
    stopDualStream,
  } = useAudioStream({
    wsSend: sendRaw,
    chunkInterval: 100,
  });

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  useEffect(() => {
    if (limits?.max_chat_images) {
      setMaxChatImages(limits.max_chat_images);
    }
  }, [limits]);

  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop());
      }
      if (alarmTimeoutRef.current) {
        clearTimeout(alarmTimeoutRef.current);
        alarmTimeoutRef.current = null;
      }
    };
  }, []);

  const currentAgent = agents.find((a) => a.id === currentAgentId);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);

  useEffect(() => {
    loadHistoryCancelledRef.current.cancelled = true;
    const myToken = { cancelled: false };
    loadHistoryCancelledRef.current = myToken;
    if (currentAgentId) {
      loadAgentHistory(currentAgentId, myToken);
    } else {
      setMessages([]);
    }
    return () => {
      myToken.cancelled = true;
    };
  }, [currentAgentId]);

  // 滚动相关
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleScroll = useCallback(() => {
    if (!chatContainerRef.current) return;

    const { scrollTop, scrollHeight, clientHeight } = chatContainerRef.current;
    const threshold = 200; // 距离底部200px以内视为接近底部
    setIsNearBottom(scrollHeight - scrollTop - clientHeight < threshold);
  }, []);

  // 监听滚动事件
  useEffect(() => {
    const chatContainer = chatContainerRef.current;
    if (chatContainer) {
      chatContainer.addEventListener('scroll', handleScroll);
      return () => chatContainer.removeEventListener('scroll', handleScroll);
    }
  }, [handleScroll]);

  // 当消息更新且接近底部时自动滚动
  useEffect(() => {
    if (isNearBottom) {
      scrollToBottom();
    }
  }, [messages, isNearBottom]);

  // 只在用户发送消息或AI开始响应时自动滚动
  const [shouldAutoScroll, setShouldAutoScroll] = useState(false);

  useEffect(() => {
    if (shouldAutoScroll) {
      scrollToBottom();
      setShouldAutoScroll(false);
    }
  }, [shouldAutoScroll]);

  const loadAgentHistory = async (agentId: string, token: { cancelled: boolean }) => {
    try {
      const data = await api.getChatHistory(`agent-${agentId}`);
      if (token.cancelled) return;
      if (data.messages) {
        const formattedMessages = data.messages.map(
          (msg: {
            id?: string;
            role: string;
            content: string;
            created_at?: string;
            thinking?: string;
            images?: string[];
          }) => ({
            id: msg.id || Math.random().toString(),
            role: msg.role === 'assistant' ? 'assistant' : 'user',
            content: msg.content,
            timestamp: msg.created_at || new Date().toISOString(),
            thinking: msg.thinking,
            images: msg.images,
          })
        );
        if (token.cancelled) return;
        setMessages(formattedMessages as Message[]);
      }
    } catch (error) {
      if (token.cancelled) return;
      console.error('加载历史消息失败:', error);
      setMessages([]);
    }
  };

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    Array.from(files).forEach((file) => {
      if (!file.type.startsWith('image/')) return;

      const reader = new FileReader();
      reader.onload = (event) => {
        const base64 = event.target?.result as string;
        setSelectedImages((prev) => {
          if (prev.length >= maxChatImages) return prev;
          return [...prev, base64];
        });
      };
      reader.readAsDataURL(file);
    });

    e.target.value = '';
  };

  const removeImage = (index: number) => {
    setSelectedImages((prev) => prev.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const getContextText = () => {
    return messages.map((m) => `${m.role === 'user' ? '用户' : '助手'}: ${m.content}`).join('\n\n');
  };

  const handleClearContext = async () => {
    if (!confirm('确定要清空当前对话的上下文吗？这将清除所有对话历史。')) return;

    const token = { cancelled: false };
    try {
      const sessionId = `agent-${currentAgentId}`;
      await api.deleteSession(sessionId);
      // 清空后重新加载历史（会创建新的空会话）
      await loadAgentHistory(currentAgentId || 'default', token);
      alert('上下文已清空');
    } catch (error) {
      console.error('清空上下文失败:', error);
      alert('清空上下文失败');
    }
  };

  const handleArchiveMemory = async () => {
    if (!confirm('确定要执行记忆归档吗？这将归档旧的记忆数据。')) return;

    try {
      const result = await api.autoArchiveProcess() as { results?: { archived?: unknown[]; merged?: unknown[] } };
      alert(
        `记忆归档完成：归档 ${result.results?.archived?.length || 0} 条，合并 ${result.results?.merged?.length || 0} 条`
      );
    } catch (error) {
      console.error('记忆归档失败:', error);
      alert('记忆归档失败');
    }
  };

  const handleAutoSummary = async () => {
    setAutoStartSummary(true);
    setShowSummaryModal(true);
  };

  // ========== 语音功能 ==========

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mediaRecorder = new MediaRecorder(stream);
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        try {
          const result = await api.speechToText(audioBlob);
          if (result.text) {
            setInput(result.text);
            // 如果是语音对话模式，自动发送
            if (isVoiceMode) {
              setTimeout(() => {
                handleSendWithText(result.text ?? '');
              }, 100);
            }
          }
        } catch (error) {
          console.error('语音识别失败:', error);
          alert('语音识别失败，请重试');
        }
        // 停止所有轨道
        stream.getTracks().forEach(track => track.stop());
        streamRef.current = null;
      };

      mediaRecorder.onerror = () => {
        console.error('录音错误');
        setIsRecording(false);
        stream.getTracks().forEach(track => track.stop());
        streamRef.current = null;
      };

      mediaRecorder.start();
      mediaRecorderRef.current = mediaRecorder;
      setIsRecording(true);
    } catch (error) {
      console.error('无法访问麦克风:', error);
      alert('无法访问麦克风，请检查权限设置');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  const playAudio = (audioData: ArrayBuffer, isLastSegment: boolean = true): Promise<void> => {
    return new Promise<void>((resolve, reject) => {
      try {
        if (audioRef.current) {
          audioRef.current.pause();
          audioRef.current = null;
        }

        const blob = new Blob([audioData], { type: 'audio/mp3' });
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        setCurrentAudioElement(audio);
        setIsAudioPlaying(true);

        driverRef.current?.setMouthOpen(0.6);

        audio.onended = () => {
          URL.revokeObjectURL(url);
          audioRef.current = null;
          setCurrentAudioElement(null);
          setIsAudioPlaying(false);
          driverRef.current?.setMouthOpen(0);
          if (isLastSegment && isVoiceMode && !isLoading) {
            setTimeout(() => {
              startRecording();
            }, 500);
          }
          resolve();
        };

        audio.play().catch(error => {
          console.error('音频播放失败:', error);
          URL.revokeObjectURL(url);
          audioRef.current = null;
          setCurrentAudioElement(null);
          setIsAudioPlaying(false);
          driverRef.current?.setMouthOpen(0);
          reject(error);
        });
      } catch (error) {
        console.error('播放音频失败:', error);
        reject(error);
      }
    });
  };

  // 设置 playAudioRef，使 WebSocket 回调可以使用
  useEffect(() => {
    playAudioRef.current = playAudio;
  }, [playAudio]);

  // ========== 双流式实时语音模式切换 ==========
  const toggleDualStreamMode = async () => {
    if (isDualStreamMode) {
      // 停止双流式：结束会话、停止 TTS、清理字幕
      stopDualStream();
      interruptTTS();
      setIsDualStreamMode(false);
      setPartialSubtitle('');
      setDualThinking(false);
      driverRef.current?.setMouthOpen(0);
    } else {
      if (!currentAgentId) {
        alert('请先选择一个 Agent');
        return;
      }
      if (!isConnected) {
        alert('WebSocket 未连接，无法启动双流式语音');
        return;
      }
      // 生成会话标识：session_id 锚定后端流水线状态，request_id 追踪单轮请求
      const sessionId = `dual-${currentAgentId}-${Date.now()}`;
      const requestId = `req-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      try {
        // 传入当前选中的引擎与音色：orpheus 引擎需携带 voice，f5-tts 仅传 engine
        await startDualStream(sessionId, currentAgentId, requestId, {
          engine: dualStreamEngine,
          voice: dualStreamEngine === 'orpheus' ? orpheusVoice : undefined,
        });
        setIsDualStreamMode(true);
        setPartialSubtitle('');
        setDualThinking(false);
      } catch (error) {
        console.error('启动双流式语音失败:', error);
        alert('启动双流式语音失败，请检查麦克风权限');
      }
    }
  };

  /**
   * 以指定引擎/音色重启双流式会话（先 stop 再 start）。
   * 引擎或音色变更需重建后端流水线（不同引擎对应不同 TTSService 实例），
   * 故切换时必须重启会话而非热更新。
   * 参数直接使用传入值，避免闭包捕获过期 state。
   */
  const restartDualStreamWithEngine = async (
    engine: 'f5-tts' | 'orpheus',
    voice: string,
  ) => {
    // 先停止当前会话：发送 end、释放麦克风、清理前端状态
    stopDualStream();
    interruptTTS();
    setPartialSubtitle('');
    setDualThinking(false);
    driverRef.current?.setMouthOpen(0);

    if (!currentAgentId || !isConnected) return;

    // 生成新会话标识（不复用旧 session_id，确保后端创建全新流水线）
    const sessionId = `dual-${currentAgentId}-${Date.now()}`;
    const requestId = `req-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    try {
      await startDualStream(sessionId, currentAgentId, requestId, {
        engine,
        voice: engine === 'orpheus' ? voice : undefined,
      });
    } catch (error) {
      console.error('切换引擎重启双流式语音失败:', error);
      setIsDualStreamMode(false);
      alert('切换引擎失败，已退出双流式模式');
    }
  };

  // 引擎切换：更新 state 并在会话激活时重启以应用新引擎
  const handleDualStreamEngineChange = (newEngine: 'f5-tts' | 'orpheus') => {
    setDualStreamEngine(newEngine);
    if (isDualStreamMode) {
      void restartDualStreamWithEngine(newEngine, orpheusVoice);
    }
  };

  // 音色切换：仅 orpheus 引擎生效，会话激活时同样需重启
  const handleOrpheusVoiceChange = (newVoice: string) => {
    setOrpheusVoice(newVoice);
    if (isDualStreamMode && dualStreamEngine === 'orpheus') {
      void restartDualStreamWithEngine(dualStreamEngine, newVoice);
    }
  };

  // 双流式模式或 TTS 播放状态变化时，同步 isAudioPlaying 以驱动 AvatarPanel
  useEffect(() => {
    if (isDualStreamMode) {
      setIsAudioPlaying(isTTSPlaying);
    }
  }, [isTTSPlaying, isDualStreamMode]);

  // 退出双流式模式时确保停止采集（组件卸载或切换 Agent）
  useEffect(() => {
    return () => {
      if (isDualStreaming) {
        stopDualStream();
      }
    };
  }, [isDualStreaming, stopDualStream]);

  const handleSendWithText = async (text: string) => {
    if ((!text.trim() && selectedImages.length === 0) || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
      images: selectedImages.length > 0 ? selectedImages : undefined,
    };

    const tempAssistantId = (Date.now() + 1).toString();
    tempAssistantIdRef.current = tempAssistantId;
    const streamingMessage: Message = {
      id: tempAssistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      tool_calls: [],
      thinking: '',
    };

    setMessages((prev) => [...prev, userMessage, streamingMessage]);
    setInput('');
    setSelectedImages([]);
    setIsLoading(true);
    setShouldAutoScroll(true);

    if (isConnected) {
      wsSendMessage(userMessage.content, userMessage.images);
    } else {
      try {
        await api.sendMessageStream(
          userMessage.content,
          (chunk: Record<string, unknown>) => {
            if (chunk.type === 'content' && chunk.content) {
              setMessages((prev) => {
                const lastMsg = prev[prev.length - 1];
                if (lastMsg && lastMsg.id === tempAssistantId) {
                  return [
                    ...prev.slice(0, -1),
                    {
                      ...lastMsg,
                      content: lastMsg.content + String(chunk.content),
                    },
                  ];
                }
                return prev;
              });
            } else if (chunk.type === 'tool_call' && chunk.tool_call) {
              const tc = chunk.tool_call as StreamToolCall;
              setMessages((prev) => {
                const lastMsg = prev[prev.length - 1];
                if (lastMsg && lastMsg.id === tempAssistantId) {
                  return [
                    ...prev.slice(0, -1),
                    {
                      ...lastMsg,
                      tool_calls: [
                        ...(lastMsg.tool_calls || []),
                        {
                          id: tc.id || Date.now().toString(),
                          name: tc.name || tc.function?.name || 'unknown',
                          arguments: tc.arguments || tc.function?.arguments,
                          status: 'pending',
                        },
                      ],
                    },
                  ];
                }
                return prev;
              });
            } else if (chunk.type === 'tool_start' && chunk.tool_name) {
              setMessages((prev) => {
                const lastMsg = prev[prev.length - 1];
                if (lastMsg && lastMsg.id === tempAssistantId && lastMsg.tool_calls) {
                  return [
                    ...prev.slice(0, -1),
                    {
                      ...lastMsg,
                      tool_calls: lastMsg.tool_calls.map((tc) =>
                        tc.name === chunk.tool_name ? { ...tc, status: 'executing' } : tc
                      ),
                    },
                  ];
                }
                return prev;
              });
            } else if (
              chunk.type === 'tool_result' &&
              chunk.tool_name &&
              chunk.result !== undefined
            ) {
              setMessages((prev) => {
                const lastMsg = prev[prev.length - 1];
                if (lastMsg && lastMsg.id === tempAssistantId && lastMsg.tool_calls) {
                  const updatedToolCalls: ToolCall[] = lastMsg.tool_calls.map((tc) =>
                    tc.name === chunk.tool_name
                      ? { ...tc, status: 'completed' as const, result: chunk.result }
                      : tc
                  );
                  return [
                    ...prev.slice(0, -1),
                    {
                      ...lastMsg,
                      tool_calls: updatedToolCalls,
                    },
                  ];
                }
                return prev;
              });
            } else if (chunk.type === 'thinking' && chunk.content) {
              setMessages((prev) => {
                const lastMsg = prev[prev.length - 1];
                if (lastMsg && lastMsg.id === tempAssistantId) {
                  return [
                    ...prev.slice(0, -1),
                    {
                      ...lastMsg,
                      thinking: (lastMsg.thinking || '') + String(chunk.content),
                    },
                  ];
                }
                return prev;
              });
            } else if (chunk.type === 'done') {
              setMessages((prev) => {
                const lastMsg = prev[prev.length - 1];
                if (lastMsg && lastMsg.id === tempAssistantId) {
                  const finalContent = lastMsg.content || '响应已完成';
                  lastDoneContentRef.current = finalContent;
                  return [
                    ...prev.slice(0, -1),
                    {
                      ...lastMsg,
                      content: finalContent,
                    },
                  ];
                }
                return prev;
              });
              setDoneTrigger(t => t + 1);
            } else if (chunk.type === 'error') {
              throw new Error(String(chunk.error ?? '未知错误'));
            }
          },
          currentAgentId || 'default',
          userMessage.images
        );
      } catch (error: unknown) {
        console.error('发送消息失败:', error);
        setMessages((prev) => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.id === tempAssistantId) {
            return [
              ...prev.slice(0, -1),
              {
                ...lastMsg,
                content: '抱歉，服务暂时不可用，请稍后重试。',
              },
            ];
          }
          return prev;
        });
        setIsLoading(false);
      }
    }
  };

  // 修改原有的 handleSend 使用新的逻辑
  const handleSend = () => {
    handleSendWithText(input);
  };

  return (
    <div className="flex h-full">
      {/* 虚拟形象面板 */}
      <AvatarPanel
        audioElement={currentAudioElement}
        isPlaying={isAudioPlaying}
        driver={activeDriver ?? undefined}
      />

      {/* 聊天区域 */}
      <div className={`flex flex-col h-full transition-all duration-300 ${layout.chatCollapsed ? 'w-16' : 'flex-1'}`}>
        {/* 折叠/展开按钮 */}
        <button
          onClick={toggleChatCollapsed}
          className="absolute top-2 right-2 z-10 p-1.5 rounded bg-[var(--color-bg-secondary)] hover:bg-[var(--color-bg-hover)] transition-colors"
          title={layout.chatCollapsed ? '展开聊天' : '折叠聊天'}
        >
          <svg
            className={`w-4 h-4 transition-transform ${layout.chatCollapsed ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </button>

        {layout.chatCollapsed ? (
          <div className="flex flex-col items-center py-4 h-full">
            <span className="text-xs text-[var(--color-text-tertiary)] writing-mode-vertical" style={{ writingMode: 'vertical-rl' }}>
              聊天
            </span>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto h-full flex flex-col w-full">
      <ChatToolbar
        currentAgent={currentAgent}
        hasMessages={messages.length > 0}
        onArchiveMemory={handleArchiveMemory}
        onClearContext={handleClearContext}
        onAutoSummary={handleAutoSummary}
        onShowSummaryModal={() => setShowSummaryModal(true)}
      />

      <DualStreamStatusBar
        isDualStreamMode={isDualStreamMode}
        dualThinking={dualThinking}
        isTTSPlaying={isTTSPlaying}
        partialSubtitle={partialSubtitle}
      />

      <MessageList
        messages={messages}
        isLoading={isLoading}
        currentAgent={currentAgent}
        chatContainerRef={chatContainerRef}
        messagesEndRef={messagesEndRef}
      />

      <ChatInput
        selectedImages={selectedImages}
        onRemoveImage={removeImage}
        currentAgent={currentAgent}
        fileInputRef={fileInputRef}
        maxChatImages={maxChatImages}
        onImageSelect={handleImageSelect}
        input={input}
        onInputChange={setInput}
        onKeyDown={handleKeyDown}
        isLoading={isLoading}
        isRecording={isRecording}
        onToggleRecording={toggleRecording}
        onCancelGeneration={cancelGeneration}
        onSend={handleSend}
        enableVoiceOutput={enableVoiceOutput}
        onToggleVoiceOutput={() => setEnableVoiceOutput(!enableVoiceOutput)}
        isVoiceMode={isVoiceMode}
        onToggleVoiceMode={() => setIsVoiceMode(!isVoiceMode)}
        isDualStreamMode={isDualStreamMode}
        onToggleDualStreamMode={toggleDualStreamMode}
        dualStreamEngine={dualStreamEngine}
        onDualStreamEngineChange={handleDualStreamEngineChange}
        orpheusVoice={orpheusVoice}
        onOrpheusVoiceChange={handleOrpheusVoiceChange}
        isConnected={isConnected}
      />

      <AlarmNotifications alarms={alarms} />

      <SummaryModal
        isOpen={showSummaryModal}
        onClose={() => {
          setShowSummaryModal(false);
          setAutoStartSummary(false);
        }}
        contextText={getContextText()}
        agentId={currentAgentId || 'default'}
        sessionId={currentAgentId || 'default'}
        autoStart={autoStartSummary}
      />
          </div>
        )}
      </div>
    </div>
  );
}
