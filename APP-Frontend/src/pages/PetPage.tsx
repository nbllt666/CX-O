/**
 * 桌宠页（路由 /pet）：透明悬浮窗主页。
 *
 * 组成：
 * - PetAvatar：VRM/Live2D 头像渲染（独立驱动实例，类型切换实时重建）
 * - PetChat：对话气泡 + 输入发送（收尾解析驱动标签下发头像）
 * - PetContextMenu：右键菜单（管理界面/弹幕窗/置顶/麦克风/屏幕共享/摄像头/抠像绿幕）
 * - useMousePassthrough：模型椭圆 + 交互矩形命中，其余区域 IPC 穿透桌面
 *
 * Task 4 接线（双流式语音互动与视觉采集）：
 * - 上行：useMicAsrUplink 麦克风 → Live WS ASR 流；asr_result 落气泡，
 *   final 自动派发对话管线（回复经聊天 WS 流式返回 + TTS 播放）
 * - 下行：useWebSocket TTS 播放 + useTtsLipSync 频谱口型；audioStore.ttsVolume
 *   经 setTTSVolume 实时生效——上下行互不阻塞
 * - 口型：useLipSyncMixer 三路汇合（tts > danmaku > mic），PetAvatar 直读
 * - 弹幕播报：useDanmakuVoice 消费 Live WS danmaku 事件（开关归设置页）
 * - 视觉采集：useVideoCapture 屏幕/摄像头；useFrameSender 节奏化帧发送
 *   （对话图像链路 /api/chat/stream images）；采集中头像区右上角状态指示
 *
 * 交互：左键按住头像区拖拽窗口（window:move IPC）；双击头像打开管理界面；
 * 右键头像区弹出菜单。麦克风/屏幕共享/摄像头开关绑定 audioStore/captureStore。
 *
 * Task 9 接线（OBS 采集支持）：
 * - 抠像绿幕开关与采集尺寸持久化于 obsStore（原 greenScreen 组件内 useState 已提升）；
 * - 采集尺寸变更经 setWindowSize IPC 调整桌宠窗（浏览器模式无窗口控制权，
 *   降级为 PetAvatar 内按预设比例缩放头像），重启后经持久化状态自动恢复尺寸。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Camera,
  ImagePlus,
  Maximize,
  MessagesSquare,
  Mic,
  MonitorUp,
  Pin,
  Power,
  ZoomIn,
  Scissors,
  Settings,
  ShieldCheck,
} from 'lucide-react';
import { useChatStore } from '../store/chatStore';
import { useAudioStore } from '../store/audioStore';
import { useCaptureStore } from '../store/captureStore';
import { useObsStore } from '../store/obsStore';
import { CAPTURE_BASE_WIDTH, CAPTURE_BASE_HEIGHT } from '../store/obsStore';
import {
  useAuthorizationStore,
  isComputerControlEnabled,
} from '../store/authorizationStore';
import { isElectron } from '../lib/isElectron';
import { useSettingsStore } from '../store/settingsStore';
import { useWebSocket } from '../hooks/useWebSocket';
import type { WebSocketMessage } from '../hooks/useWebSocket';
import { useLiveWebSocket } from '../hooks/useLiveWebSocket';
import { useMicAsrUplink } from '../hooks/useMicAsrUplink';
import { useVideoCapture } from '../hooks/capture/useVideoCapture';
import type { CaptureSourceKind } from '../hooks/capture/useVideoCapture';
import { useFrameSender } from '../hooks/capture/useFrameSender';
import { chatApi } from '../api/clients/chat';
import type { IAvatarDriver } from '../avatar/types';
import { PetAvatar } from '../components/pet/PetAvatar';
import { PetChat } from '../components/pet/PetChat';
import type { PetChatHandle } from '../components/pet/PetChat';
import { PetContextMenu } from '../components/pet/PetContextMenu';
import type { PetContextMenuItem } from '../components/pet/PetContextMenu';
import { useMousePassthrough } from './pet/useMousePassthrough';
import {
  DEFAULT_HIT_ELLIPSE,
  type HitEllipse,
} from './pet/hitGeometry';
import { useTtsLipSync } from './pet/useTtsLipSync';
import { useDanmakuVoice } from './pet/useDanmakuVoice';
import { useLipSyncMixer } from './pet/useLipSyncMixer';
import { vadStatusToSpeaking } from './pet/vad';
import {
  advanceDragGesture,
  createDragGestureState,
  isDragGestureClick,
  type DragGestureState,
} from './pet/dragGesture';

/** OBS 抠像绿幕底色（ chroma key 标准绿 ） */
const GREEN_SCREEN_COLOR = '#00ff00';

function nowIso(): string {
  return new Date().toISOString();
}

export default function PetPage() {
  const { t } = useTranslation();
  const currentAgentId = useChatStore((s) => s.currentAgentId);

  // ── Task 4 状态存储绑定（audioStore 全持久化 / captureStore 开关不持久化） ──
  const micEnabled = useAudioStore((s) => s.micEnabled);
  const setMicEnabled = useAudioStore((s) => s.setMicEnabled);
  const micGain = useAudioStore((s) => s.micGain);
  const ttsVolume = useAudioStore((s) => s.ttsVolume);
  const danmakuVoiceEnabled = useAudioStore((s) => s.danmakuVoiceEnabled);
  const screenActive = useCaptureStore((s) => s.screenActive);
  const setScreenActive = useCaptureStore((s) => s.setScreenActive);
  const cameraActive = useCaptureStore((s) => s.cameraActive);
  const setCameraActive = useCaptureStore((s) => s.setCameraActive);
  const visionEnabled = useCaptureStore((s) => s.visionEnabled);
  const frameMode = useCaptureStore((s) => s.frameMode);
  const frameIntervalSec = useCaptureStore((s) => s.frameIntervalSec);

  // ── Task 9 状态存储绑定（obsStore：抠像绿幕 + 采集尺寸，全持久化） ──
  const greenScreen = useObsStore((s) => s.greenScreen);
  const toggleGreenScreen = useObsStore((s) => s.toggleGreenScreen);
  const captureWidth = useObsStore((s) => s.captureWidth);
  const captureHeight = useObsStore((s) => s.captureHeight);
  const cycleCaptureSize = useObsStore((s) => s.cycleCaptureSize);
  const setCaptureSize = useObsStore((s) => s.setCaptureSize);

  // ── Task 4 电脑控制授权状态（授权为永久授权，撤销后不自动恢复） ──
  const computerControlAuthorized = useAuthorizationStore((s) => s.authorized);
  const computerControlRunning = useAuthorizationStore((s) => s.running);
  const authorizeComputerControl = useAuthorizationStore((s) => s.authorize);
  const revokeComputerControl = useAuthorizationStore((s) => s.revoke);
  // 电脑控制工具可执行门禁：未授权（即使 CXFC 已注册）或服务未运行时均不可用
  const computerControlEnabled = isComputerControlEnabled(
    computerControlAuthorized,
    computerControlRunning,
  );

  const [isLoading, setIsLoading] = useState(false);
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);
  // 主进程创建桌宠窗时 alwaysOnTop:true，本地初值与之对齐
  const [alwaysOnTop, setAlwaysOnTop] = useState(true);
  const [isDragging, setIsDragging] = useState(false);
  const [scaleSliderOpen, setScaleSliderOpen] = useState(false);
  const [driver, setDriver] = useState<IAvatarDriver | null>(null);
  // 服务端 VAD 说话状态（Live WS vad_status 驱动 mic 口型通道）
  const [micSpeaking, setMicSpeaking] = useState(false);
  const avatarScale = useSettingsStore((s) => s.avatarType === 'vrm' ? s.vrm.scale : s.live2d.scale);
  const avatarType = useSettingsStore((s) => s.avatarType);
  const setVRMSettings = useSettingsStore((s) => s.setVRMSettings);
  const setLive2DSettings = useSettingsStore((s) => s.setLive2DSettings);

  // 缩放与窗口联动：桌宠模型始终填满窗口，放大时同步放大窗口 → 模型更大且不被裁切。
  // 仅 VRM 生效（Live2D 走固定布局），且仅在 Electron 有窗口控制权时下发 IPC。
  useEffect(() => {
    if (!isElectron()) return;
    if (avatarType !== 'vrm') return;
    const w = Math.round(CAPTURE_BASE_WIDTH * avatarScale);
    const h = Math.round(CAPTURE_BASE_HEIGHT * avatarScale);
    void window.electronAPI?.setWindowSize(w, h);
    setCaptureSize(w, h);
  }, [avatarType, avatarScale, setCaptureSize]);

  const avatarContainerRef = useRef<HTMLDivElement>(null);
  const chatAreaRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const chatRef = useRef<PetChatHandle>(null);
  const accumulatedRef = useRef('');
  const dragStateRef = useRef<DragGestureState | null>(null);
  // ASR 进行中的气泡 id（interim 就地更新，final 派发后清空）
  const asrMsgIdRef = useRef<string | null>(null);
  // 流式会话互斥闸（语音派发 / 帧发送 / 定时抽帧共用）
  const isLoadingRef = useRef(false);
  isLoadingRef.current = isLoading;

  // 桌宠窗独立加载 /pet，需自行拉取 Agent 列表以确定 currentAgentId
  useEffect(() => {
    const state = useChatStore.getState();
    if (state.agents.length === 0) {
      void state.fetchAgents();
    }
  }, []);

  // 重启恢复电脑控制授权：启动时读主进程 getComputerControlAuth 权威值
  useEffect(() => {
    void useAuthorizationStore.getState().restore();
  }, []);

  // 透明窗体底色：绿幕模式铺标准抠像绿，其余保持透明
  useEffect(() => {
    const bg = greenScreen ? GREEN_SCREEN_COLOR : 'transparent';
    document.body.style.background = bg;
    document.documentElement.style.background = bg;
    return () => {
      document.body.style.background = 'transparent';
      document.documentElement.style.background = 'transparent';
    };
  }, [greenScreen]);

  // ── 助手流式事件统一处理（聊天 WS 与带图 SSE 共用同一收口） ──
  const handleAssistantStreamEvent = useCallback(
    (type: 'content' | 'done' | 'error', payload: { content?: string; error?: string }) => {
      if (type === 'content' && payload.content) {
        accumulatedRef.current += payload.content;
        chatRef.current?.updateLastAssistantMessage(payload.content);
      } else if (type === 'done') {
        setIsLoading(false);
        const finalContent = accumulatedRef.current;
        accumulatedRef.current = '';
        chatRef.current?.finalizeLastAssistantMessage(finalContent);
      } else if (type === 'error') {
        setIsLoading(false);
        accumulatedRef.current = '';
        chatRef.current?.finalizeLastAssistantMessage(
          t('pet.chat.error', { message: payload.error ?? 'unknown' }),
        );
      }
    },
    [t],
  );

  // 聊天 WS：content 流式累积 → 气泡增量；done/cancelled 收尾解析标签；error 落错误文案
  const handleWsMessage = useCallback(
    (data: WebSocketMessage) => {
      if (data.type === 'content' && data.content) {
        handleAssistantStreamEvent('content', { content: data.content });
      } else if (data.type === 'done' || data.type === 'cancelled') {
        handleAssistantStreamEvent('done', {});
      } else if (data.type === 'error') {
        const message =
          typeof data.error === 'string' ? data.error : (data.error?.message ?? 'unknown');
        handleAssistantStreamEvent('error', { error: message });
      }
    },
    [handleAssistantStreamEvent],
  );

  const { isConnected, isTTSPlaying, sendMessage, getTTSAnalyser, setTTSVolume } = useWebSocket({
    agentId: currentAgentId || 'default',
    timeout: 60,
    onMessage: handleWsMessage,
    onError: () => {
      setIsLoading(false);
    },
  });

  // TTS 音量（audioStore.ttsVolume）实时生效；播放器懒创建前暂存、创建时应用
  useEffect(() => {
    setTTSVolume(ttsVolume);
  }, [ttsVolume, setTTSVolume]);

  // 口型音源一：对话 TTS 频谱（渲染循环直读，不经 React 重渲染）
  const ttsLip = useTtsLipSync({
    getAnalyser: getTTSAnalyser,
    isPlaying: isTTSPlaying,
  });

  // ── 弹幕语音播报（开关归设置页 audioStore.danmakuVoiceEnabled） ──
  const handleDanmakuSpeakStart = useCallback(
    (text: string) => {
      chatRef.current?.addMessage({
        id: `dv-${Date.now()}`,
        role: 'assistant',
        content: `${t('pet.danmakuVoice.bubblePrefix')}${text}`,
        timestamp: nowIso(),
      });
    },
    [t],
  );

  const {
    notifyDanmaku,
    isPlaying: isDanmakuSpeaking,
    volumeRef: danmakuVolumeRef,
    vowelWeightsRef: danmakuVowelRef,
  } = useDanmakuVoice({
    enabled: danmakuVoiceEnabled,
    volume: ttsVolume,
    onSpeakStart: handleDanmakuSpeakStart,
  });

  // ── 助手回复派发（打字输入与 ASR final 共用；用户气泡由 caller 负责落） ──
  const dispatchToAssistant = useCallback(
    (message: string) => {
      accumulatedRef.current = '';
      chatRef.current?.addMessage({
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: '',
        timestamp: nowIso(),
      });
      setIsLoading(true);
      const sent = isConnected ? sendMessage(message) : false;
      if (!sent) {
        setIsLoading(false);
        chatRef.current?.finalizeLastAssistantMessage(t('pet.chat.unreachable'));
      }
    },
    [isConnected, sendMessage, t],
  );

  // ── Live WS：VAD 状态 + ASR 结果 + 弹幕事件 + 音频上行通道 ──
  const handleVadStatus = useCallback((data: { status: string }) => {
    setMicSpeaking((prev) => vadStatusToSpeaking(data.status, prev));
  }, []);

  const handleAsrResult = useCallback(
    (data: { text: string; is_final: boolean }) => {
      const text = data.text.trim();
      if (!text) return;
      // interim 就地更新同一气泡；一段话一个气泡
      if (!asrMsgIdRef.current) {
        const id = `asr-${Date.now()}`;
        asrMsgIdRef.current = id;
        chatRef.current?.addMessage({
          id,
          role: 'user',
          content: text,
          timestamp: nowIso(),
        });
      } else {
        chatRef.current?.updateMessageContent(asrMsgIdRef.current, text);
      }
      if (data.is_final) {
        asrMsgIdRef.current = null;
        // 对话进行中不并发派发，识别文本保留气泡待用户稍后处理
        if (!isLoadingRef.current) {
          dispatchToAssistant(text);
        }
      }
    },
    [dispatchToAssistant],
  );

  const { sendAudio } = useLiveWebSocket({
    onDanmaku: notifyDanmaku,
    onVadStatus: handleVadStatus,
    onASRResult: handleAsrResult,
  });

  // 麦克风关闭时复位 VAD 说话状态（防口型卡在张开位）
  useEffect(() => {
    if (!micEnabled) setMicSpeaking(false);
  }, [micEnabled]);

  // ── 采集失败反馈：开关回退 + 气泡提示 ──
  const showCaptureError = useCallback(
    (kind: 'mic' | CaptureSourceKind) => {
      const key =
        kind === 'mic'
          ? 'pet.capture.micError'
          : kind === 'screen'
            ? 'pet.capture.screenError'
            : 'pet.capture.cameraError';
      chatRef.current?.addMessage({
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: t(key),
        timestamp: nowIso(),
      });
    },
    [t],
  );

  // 口型音源三：麦克风上行（ASR 流 + VAD 驱动本地频谱口型）
  const micUplink = useMicAsrUplink({
    enabled: micEnabled,
    gain: micGain,
    sendAudio,
    speaking: micSpeaking,
    onError: () => {
      setMicEnabled(false);
      showCaptureError('mic');
    },
  });

  // ── 视觉采集：屏幕 / 摄像头（默认关闭，重启不恢复；系统级停止回写开关） ──
  const screenCapture = useVideoCapture({
    kind: 'screen',
    active: screenActive,
    onError: () => {
      setScreenActive(false);
      showCaptureError('screen');
    },
    onEnded: () => setScreenActive(false),
  });
  const cameraCapture = useVideoCapture({
    kind: 'camera',
    active: cameraActive,
    onError: () => {
      setCameraActive(false);
      showCaptureError('camera');
    },
    onEnded: () => setCameraActive(false),
  });

  // ── 画面帧发送链路：对话图像链路（/api/chat/stream images，WS 不支持带图） ──
  const sendFrame = useCallback(
    (dataUrl: string, kind: CaptureSourceKind) => {
      if (isLoadingRef.current) return;
      // 主动视觉总开关：关闭则不向 LLM 发送画面帧
      if (!visionEnabled) return;
      const prompt = t(
        kind === 'screen' ? 'pet.capture.framePromptScreen' : 'pet.capture.framePromptCamera',
      );
      chatRef.current?.addMessage({
        id: `u-${Date.now()}`,
        role: 'user',
        content: prompt,
        timestamp: nowIso(),
      });
      accumulatedRef.current = '';
      chatRef.current?.addMessage({
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: '',
        timestamp: nowIso(),
      });
      setIsLoading(true);
      void chatApi
        .sendMessageStream(
          prompt,
          (chunk) => {
            const type = chunk.type as string | undefined;
            if (type === 'content' && typeof chunk.content === 'string') {
              handleAssistantStreamEvent('content', { content: chunk.content });
            } else if (type === 'done') {
              handleAssistantStreamEvent('done', {});
            } else if (type === 'error') {
              handleAssistantStreamEvent('error', {
                error: typeof chunk.message === 'string' ? chunk.message : 'unknown',
              });
            }
            // session/thinking/tool_* 等分块在桌宠气泡从简忽略
          },
          currentAgentId || 'default',
          [dataUrl],
        )
        .catch(() => {
          setIsLoading(false);
          accumulatedRef.current = '';
          chatRef.current?.finalizeLastAssistantMessage(t('pet.chat.unreachable'));
        });
    },
    [t, currentAgentId, handleAssistantStreamEvent, visionEnabled],
  );

  const { sendNow } = useFrameSender({
    sources: [
      { kind: 'screen', active: screenCapture.isCapturing, captureFrame: screenCapture.captureFrame },
      { kind: 'camera', active: cameraCapture.isCapturing, captureFrame: cameraCapture.captureFrame },
    ],
    mode: frameMode,
    intervalSec: frameIntervalSec,
    sendFrame,
    canSend: () => visionEnabled && !isLoadingRef.current,
  });

  // ── 口型三路人混：tts > danmaku > mic，PetAvatar 直读混合输出 ──
  const { volumeRef: lipVolumeRef, vowelWeightsRef: lipVowelRef } = useLipSyncMixer({
    tts: {
      active: isTTSPlaying,
      volumeRef: ttsLip.volumeRef,
      vowelWeightsRef: ttsLip.vowelWeightsRef,
    },
    danmaku: {
      active: isDanmakuSpeaking,
      volumeRef: danmakuVolumeRef,
      vowelWeightsRef: danmakuVowelRef,
    },
    mic: {
      active: micSpeaking && micUplink.isActive,
      volumeRef: micUplink.volumeRef,
      vowelWeightsRef: micUplink.vowelWeightsRef,
    },
  });

  // 鼠标穿透：头像椭圆 + 聊天条 + 右键菜单命中拦截，其余穿透桌面
  // 命中椭圆跟随模型缩放：模型放大命中区随之放大，缩小则缩小，让非模型区域可穿透
  const hitEllipse = useMemo<HitEllipse>(() => {
    if (avatarType !== 'vrm') return DEFAULT_HIT_ELLIPSE;
    // 屏幕上的模型占比随 scale^(1-p) 变化（与 vrmEngine 取景一致），椭圆按同比例缩放
    const k = Math.sqrt(avatarScale);
    return {
      cx: DEFAULT_HIT_ELLIPSE.cx,
      cy: DEFAULT_HIT_ELLIPSE.cy,
      rx: Math.min(DEFAULT_HIT_ELLIPSE.rx * k, 0.5),
      ry: Math.min(DEFAULT_HIT_ELLIPSE.ry * k, 0.5),
    };
  }, [avatarType, avatarScale]);
  useMousePassthrough({
    avatarContainerRef,
    interactiveRefs: [chatAreaRef, menuRef],
    hitEllipse,
    enabled: !isDragging,
  });

  // 发送：PetChat 已落用户气泡，这里补助手占位 → WS；失败立即收尾错误文案
  const handleSend = useCallback(
    (message: string) => {
      if (isLoading) return;
      dispatchToAssistant(message);
    },
    [isLoading, dispatchToAssistant],
  );

  // 拖拽移动：左键按住头像区，位移增量经 window:move IPC 下发
  const handlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    setIsDragging(true);
    void window.electronAPI?.setIgnoreMouseEvents(false);
    dragStateRef.current = createDragGestureState(e.screenX, e.screenY);
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const handlePointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    if (!drag) return;
    const { dx, dy, moved } = advanceDragGesture(drag, e.screenX, e.screenY);
    if (moved) {
      void window.electronAPI?.moveWindow(dx, dy);
    }
  };

  const handlePointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    dragStateRef.current = null;
    setIsDragging(false);
    if (isDragGestureClick(drag)) {
      const rect = avatarContainerRef.current?.getBoundingClientRect();
      const anchor = rect
        ? { x: rect.left + rect.width * 0.6, y: rect.top + rect.height * 0.38 }
        : { x: e.clientX, y: e.clientY };
      setMenuPos((current) => (current ? null : anchor));
    }
    void window.electronAPI?.setIgnoreMouseEvents(false);
  };

  const closeMenu = useCallback(() => setMenuPos(null), []);

  const handleContextMenu = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const rect = avatarContainerRef.current?.getBoundingClientRect();
    setMenuPos(
      rect
        ? { x: rect.left + rect.width * 0.6, y: rect.top + rect.height * 0.38 }
        : { x: e.clientX, y: e.clientY },
    );
  };

  const menuItems: PetContextMenuItem[] = [
    {
      key: 'open-management',
      label: t('pet.menu.openManagement'),
      icon: <Settings className="h-3.5 w-3.5" />,
      onSelect: () => {
        void window.electronAPI?.openManagementWindow();
        closeMenu();
      },
    },
    {
      key: 'toggle-danmaku',
      label: t('pet.menu.toggleDanmaku'),
      icon: <MessagesSquare className="h-3.5 w-3.5" />,
      // 菜单项存在性归本任务；弹幕窗功能有效性归 Task 5 判据
      onSelect: () => {
        void window.electronAPI?.toggleDanmakuWindow();
        closeMenu();
      },
    },
    {
      key: 'always-on-top',
      label: t('pet.menu.alwaysOnTop'),
      icon: <Pin className="h-3.5 w-3.5" />,
      checked: alwaysOnTop,
      onSelect: () => {
        const next = !alwaysOnTop;
        setAlwaysOnTop(next);
        void window.electronAPI?.setAlwaysOnTop(next);
        closeMenu();
      },
    },
    {
      key: 'microphone',
      label: t('pet.menu.microphone'),
      icon: <Mic className="h-3.5 w-3.5" />,
      checked: micEnabled,
      onSelect: () => {
        setMicEnabled(!micEnabled);
        closeMenu();
      },
    },
    {
      key: 'screen-share',
      label: t('pet.menu.screenShare'),
      icon: <MonitorUp className="h-3.5 w-3.5" />,
      checked: screenActive,
      onSelect: () => {
        setScreenActive(!screenActive);
        closeMenu();
      },
    },
    {
      key: 'camera',
      label: t('pet.menu.camera'),
      icon: <Camera className="h-3.5 w-3.5" />,
      checked: cameraActive,
      onSelect: () => {
        setCameraActive(!cameraActive);
        closeMenu();
      },
    },
    {
      // Task 4 电脑控制授权入口：授权优先于工具可执行状态（未授权不得仅因注册成功即可用）。
      // 授权为永久授权；授权/撤销均需用户确认，主动撤销后不自动恢复。
      key: 'computer-control-auth',
      label: `${t('pet.menu.computerControl')}：${
        !computerControlRunning
          ? t('pet.computerControl.notAvailable')
          : computerControlAuthorized
            ? t('pet.computerControl.authorized')
            : t('pet.computerControl.unauthorized')
      }`,
      icon: <ShieldCheck className="h-3.5 w-3.5" />,
      // 勾选态 = 工具可执行门禁（已授权且服务运行），注册失败时保持不虚高
      checked: computerControlEnabled,
      onSelect: () => {
        if (computerControlAuthorized) {
          if (window.confirm(t('pet.computerControl.revokeConfirm'))) {
            void revokeComputerControl();
          }
        } else if (window.confirm(t('pet.computerControl.authorizeConfirm'))) {
          void authorizeComputerControl();
        }
        closeMenu();
      },
    },
    {
      key: 'green-screen',
      label: t('pet.menu.greenScreen'),
      icon: <Scissors className="h-3.5 w-3.5" />,
      checked: greenScreen,
      // 状态归 obsStore（持久化）；OBS 透明/绿幕真实采集兼容性实测归 Task 10
      onSelect: () => {
        toggleGreenScreen();
        closeMenu();
      },
    },
    {
      key: 'capture-size',
      label: t('pet.obs.captureSize', { size: `${captureWidth}×${captureHeight}` }),
      icon: <Maximize className="h-3.5 w-3.5" />,
      // 循环切换预设档；窗口尺寸经上方 effect 下发 IPC，头像自适应归 PetAvatar
      onSelect: () => {
        cycleCaptureSize();
        closeMenu();
      },
    },
    {
      key: 'avatar-scale',
      label: t('pet.menu.avatarScale', { scale: `${Math.round(avatarScale * 100)}%` }),
      icon: <ZoomIn className="h-3.5 w-3.5" />,
      slider: scaleSliderOpen
        ? {
            value: avatarScale,
            min: 0.6,
            max: 2.0,
            step: 0.05,
            onChange: (value) => {
              if (avatarType === 'vrm') setVRMSettings({ scale: value });
              else if (avatarType === 'live2d') setLive2DSettings({ scale: value });
            },
          }
        : undefined,
      onSelect: () => {
        setScaleSliderOpen((open) => !open);
      },
    },
    {
      key: 'close-pet',
      label: t('pet.menu.closePet'),
      icon: <Power className="h-3.5 w-3.5" />,
      onSelect: () => {
        void window.electronAPI?.closePet();
        closeMenu();
      },
    },
  ];

  // 采集状态指示：任一链路真实采集中时头像区右上角亮标（只读，不拦截鼠标）
  const captureIndicators = [
    { on: micUplink.isActive, label: t('pet.capture.micOn'), icon: <Mic className="h-3 w-3 text-primary" /> },
    { on: screenCapture.isCapturing, label: t('pet.capture.screenOn'), icon: <MonitorUp className="h-3 w-3 text-primary" /> },
    { on: cameraCapture.isCapturing, label: t('pet.capture.cameraOn'), icon: <Camera className="h-3 w-3 text-primary" /> },
  ].filter((item) => item.on);

  // 发送画面入口：总开关开启且任一采集开关开启时出现在输入行左侧
  const frameSendAccessory =
    visionEnabled && (screenActive || cameraActive) ? (
      <button
        type="button"
        onClick={() => sendNow()}
        disabled={isLoading}
        aria-label={t('pet.capture.sendFrame')}
        title={t('pet.capture.sendFrame')}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/85 text-primary-foreground transition-opacity duration-fast hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <ImagePlus className="h-3.5 w-3.5" />
      </button>
    ) : null;

  return (
    <div
      className="flex h-full w-full select-none flex-col"
      style={{ backgroundColor: 'transparent' }}
      onPointerUp={handlePointerUp}
    >
      {/* 头像区：拖拽 / 双击 / 右键菜单 */}
      <div
        ref={avatarContainerRef}
        className="relative"
        style={{ height: '72%', backgroundColor: 'transparent' }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={() => {
          dragStateRef.current = null;
          setIsDragging(false);
          void window.electronAPI?.setIgnoreMouseEvents(false);
        }}
        onDoubleClick={() => {
          closeMenu();
          void window.electronAPI?.openManagementWindow();
        }}
        onContextMenu={handleContextMenu}
      >
        <PetAvatar volumeRef={lipVolumeRef} vowelWeightsRef={lipVowelRef} onDriverReady={setDriver} />

        {/* 采集状态指示（真实采集中才亮标） */}
        {captureIndicators.length > 0 && (
          <div className="pointer-events-none absolute right-2 top-2 flex gap-1">
            {captureIndicators.map((item) => (
              <span
                key={item.label}
                aria-label={item.label}
                title={item.label}
                className="glass-panel flex h-5 w-5 items-center justify-center rounded-md"
              >
                {item.icon}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 对话区：整体注册为穿透命中交互区 */}
      <div ref={chatAreaRef} className="min-h-0 flex-1" style={{ backgroundColor: 'transparent' }}>
        <PetChat
          ref={chatRef}
          driver={driver}
          onSend={handleSend}
          isLoading={isLoading}
          isConnected={isConnected}
          inputAccessory={frameSendAccessory}
        />
      </div>

      <PetContextMenu position={menuPos} items={menuItems} onClose={closeMenu} menuRef={menuRef} />
    </div>
  );
}
