import { useState, useRef, useEffect, useCallback } from 'react';
import { PetAvatar, type PetAvatarHandle } from '../components/PetAvatar';
import { PetChat, type PetChatHandle } from '../components/PetChat';
import { PetAudioPanel } from '../components/PetAudioPanel';
import { usePetMousePassthrough } from '../hooks/usePetMousePassthrough';
import { useWebSocket, type WebSocketMessage } from '../hooks/useWebSocket';
import { useChatStore } from '../store/chatStore';
import type { IAvatarDriver } from '../components/Avatar/AvatarDriver';

interface ContextMenuItem {
  label: string;
  action: () => void;
  icon?: React.ReactNode;
}

export function PetPage() {
  const [mouthOpenY, setMouthOpenY] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [isAlwaysOnTop, setIsAlwaysOnTop] = useState(false);
  const [micEnabled, setMicEnabled] = useState(false);
  const [petDriver, setPetDriver] = useState<IAvatarDriver | null>(null);

  const petAvatarRef = useRef<PetAvatarHandle>(null);
  const avatarContainerRef = useRef<HTMLDivElement>(null);
  const chatRef = useRef<PetChatHandle>(null);
  const tempAssistantIdRef = useRef<string>('');
  const accumulatedContentRef = useRef<string>('');
  const isDraggingRef = useRef(false);
  const dragStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  const { currentAgentId } = useChatStore();

  // Set transparent background on mount
  useEffect(() => {
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = '';
      document.documentElement.style.background = '';
    };
  }, []);

  // Mouse passthrough hook
  usePetMousePassthrough({
    containerRef: avatarContainerRef,
    enabled: true,
  });

  // WebSocket for chat
  const handleWebSocketMessage = useCallback(
    (data: WebSocketMessage) => {
      if (data.type === 'content' && data.content) {
        accumulatedContentRef.current += data.content;
        if (chatRef.current) {
          chatRef.current.updateLastAssistantMessage(data.content);
        }
      } else if (data.type === 'done') {
        setIsLoading(false);
        const finalContent = accumulatedContentRef.current;
        if (chatRef.current) {
          chatRef.current.finalizeLastAssistantMessage(finalContent);
        }
        accumulatedContentRef.current = '';
      } else if (data.type === 'error') {
        setIsLoading(false);
        accumulatedContentRef.current = '';
        if (chatRef.current) {
          chatRef.current.finalizeLastAssistantMessage(`抱歉，发生错误：${data.error || '未知错误'}`);
        }
      }
    },
    [],
  );

  const { isConnected, sendMessage: wsSendMessage } = useWebSocket({
    agentId: currentAgentId || 'default',
    timeout: 60,
    onMessage: handleWebSocketMessage,
    onError: (error) => {
      console.error('Pet WebSocket error:', error);
      setIsLoading(false);
    },
  });

  // Send message handler
  const handleSend = useCallback((message: string) => {
    if (isLoading) return;

    const tempAssistantId = (Date.now() + 1).toString();
    tempAssistantIdRef.current = tempAssistantId;
    accumulatedContentRef.current = '';

    // Add assistant placeholder via chatRef
    if (chatRef.current) {
      chatRef.current.addMessage({
        id: tempAssistantId,
        role: 'assistant',
        content: '',
        timestamp: new Date().toISOString(),
      });
    }

    setIsLoading(true);

    if (isConnected) {
      wsSendMessage(message);
    }
  }, [isLoading, isConnected, wsSendMessage]);

  // Window dragging via IPC
  const handleAvatarMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return; // Only left click
    isDraggingRef.current = true;
    dragStartRef.current = { x: e.screenX, y: e.screenY };
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDraggingRef.current) return;
    const dx = e.screenX - dragStartRef.current.x;
    const dy = e.screenY - dragStartRef.current.y;
    dragStartRef.current = { x: e.screenX, y: e.screenY };

    const electronAPI = (window as unknown as { electronAPI?: { moveWindow: (x: number, y: number) => void } }).electronAPI;
    if (electronAPI?.moveWindow) {
      electronAPI.moveWindow(dx, dy);
    }
  }, []);

  const handleMouseUp = useCallback(() => {
    isDraggingRef.current = false;
  }, []);

  // Double-click to focus main window
  const handleDoubleClick = useCallback(() => {
    const electronAPI = (window as unknown as { electronAPI?: { openPetWindow: () => Promise<void> } }).electronAPI;
    void electronAPI?.openPetWindow();
  }, []);

  // Right-click context menu
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  const handleClosePet = useCallback(() => {
    const electronAPI = (window as unknown as { electronAPI?: { closePetWindow: () => void } }).electronAPI;
    if (electronAPI?.closePetWindow) {
      electronAPI.closePetWindow();
    }
    closeContextMenu();
  }, [closeContextMenu]);

  const handleFocusMain = useCallback(() => {
    const electronAPI = (window as unknown as { electronAPI?: { openPetWindow: () => void } }).electronAPI;
    if (electronAPI?.openPetWindow) {
      electronAPI.openPetWindow();
    }
    closeContextMenu();
  }, [closeContextMenu]);

  const handleToggleAlwaysOnTop = useCallback(() => {
    setIsAlwaysOnTop(prev => !prev);
    closeContextMenu();
  }, [closeContextMenu]);

  const handleToggleMic = useCallback(() => {
    setMicEnabled(prev => !prev);
    closeContextMenu();
  }, [closeContextMenu]);

  const contextMenuItems: ContextMenuItem[] = [
    {
      label: '关闭悬浮窗',
      action: handleClosePet,
      icon: (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      ),
    },
    {
      label: '返回主窗口',
      action: handleFocusMain,
      icon: (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
        </svg>
      ),
    },
    {
      label: isAlwaysOnTop ? '取消置顶' : '置顶',
      action: handleToggleAlwaysOnTop,
      icon: (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
        </svg>
      ),
    },
    {
      label: micEnabled ? '关闭麦克风' : '开启麦克风',
      action: handleToggleMic,
      icon: (
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
        </svg>
      ),
    },
  ];

  // Close context menu on click outside
  useEffect(() => {
    if (!contextMenu) return;
    const handleClick = () => closeContextMenu();
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, [contextMenu, closeContextMenu]);

  return (
    <div
      className="w-screen h-screen flex flex-col select-none"
      style={{ backgroundColor: 'transparent' }}
      onMouseUp={handleMouseUp}
    >
      {/* Avatar area - 60% vertical space */}
      <div
        ref={avatarContainerRef}
        className="relative"
        style={{ height: '60%', backgroundColor: 'transparent', pointerEvents: 'auto' }}
        onMouseDown={handleAvatarMouseDown}
        onMouseMove={handleMouseMove}
        onContextMenu={handleContextMenu}
        onDoubleClick={handleDoubleClick}
      >
        <PetAvatar
          ref={petAvatarRef}
          mouthOpenY={mouthOpenY}
          onDriverReady={setPetDriver}
        />
      </div>

      {/* Chat area */}
      <div
        className="flex-1 flex flex-col"
        style={{ backgroundColor: 'transparent', pointerEvents: 'none' }}
      >
        <PetChat
          ref={chatRef}
          driver={petDriver}
          onSend={handleSend}
          isLoading={isLoading}
          enableTTS
        />
      </div>

      {/* Audio panel */}
      <div style={{ backgroundColor: 'transparent', pointerEvents: 'none' }}>
        <PetAudioPanel onMouthOpenYChange={setMouthOpenY} />
      </div>

      {/* Context menu */}
      {contextMenu && (
        <div
          className="fixed z-50 py-1 rounded-lg shadow-lg border border-[var(--color-border)]/50 backdrop-blur-md"
          style={{
            left: contextMenu.x,
            top: contextMenu.y,
            backgroundColor: 'rgba(30, 30, 40, 0.9)',
            pointerEvents: 'auto',
          }}
        >
          {contextMenuItems.map((item, index) => (
            <button
              key={index}
              onClick={item.action}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors text-left"
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
