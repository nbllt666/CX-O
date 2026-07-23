import { useState, useEffect, useRef } from 'react';
import { Routes, Route, Navigate, Link } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { DashboardPage } from './pages/DashboardPage';
import { ChatPage } from './pages/ChatPage';
import { MemoriesPage } from './pages/MemoriesPage';
import { ArchivePage } from './pages/ArchivePage';
import { SettingsPage } from './pages/SettingsPage';
import { AcpPage } from './pages/AcpPage';
import PluginsPage from './pages/PluginsPage';
import { ToolsPage } from './pages/ToolsPage';
import { AgentsPage } from './pages/AgentsPage';
import { MemoryAgentPage } from './pages/MemoryAgentPage';
import { VectorDataPage } from './pages/VectorDataPage';
import { LivePage } from './pages/LivePage';
import { LiveSplitPage } from './pages/LiveSplitPage';
import { AvatarSource } from './pages/live/AvatarSource';
import { DanmakuSource } from './pages/live/DanmakuSource';
import { SubtitleSource } from './pages/live/SubtitleSource';
import { AudioPanel } from './pages/live/AudioPanel';
import { AudioPanelOBS } from './pages/live/AudioPanelOBS';
import { AudioTestPage } from './pages/AudioTestPage';
import { AudioWorkstationPage } from './pages/AudioWorkstationPage';
import { PetPage } from './pages/PetPage';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ConnectionSetup } from './components/ConnectionSetup';
import { initBackendUrl } from './api/client';
import { initElectronStorage } from './lib/electronStorage';
import { useSettingsStore } from './store/settingsStore';

function NotFound() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--color-bg-primary)] text-center px-4">
      <h1 className="text-6xl font-bold text-[var(--color-text-primary)] mb-4">404</h1>
      <p className="text-lg text-[var(--color-text-secondary)] mb-6">页面未找到</p>
      <Link
        to="/chat"
        className="px-4 py-2 rounded bg-[var(--color-accent)] text-white hover:opacity-90 transition-opacity"
      >
        返回对话
      </Link>
    </div>
  );
}

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [isChecking, setIsChecking] = useState(true);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    checkBackendConnection();
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const checkBackendConnection = async () => {
    // Initialise Electron IPC-backed URL & storage before any API call
    await initElectronStorage();
    const backendUrl = await initBackendUrl();

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);

      const response = await fetch(`${backendUrl}/health`, {
        method: 'GET',
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (cancelledRef.current) return;
      if (response.ok) {
        setIsConnected(true);
        // 连接成功后获取后端限制配置
        useSettingsStore.getState().fetchLimits();
      } else {
        setIsConnected(false);
      }
    } catch {
      if (cancelledRef.current) return;
      setIsConnected(false);
    } finally {
      if (!cancelledRef.current) {
        setIsChecking(false);
      }
    }
  };

  const handleConnected = () => {
    setIsConnected(true);
  };

  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg-primary)]">
        <div className="text-[var(--color-text-secondary)]">检查连接...</div>
      </div>
    );
  }

  if (!isConnected) {
    return <ConnectionSetup onConnected={handleConnected} />;
  }

  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<AppLayout />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="memories" element={<MemoriesPage />} />
          <Route path="archive" element={<ArchivePage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="acp" element={<AcpPage />} />
          <Route path="plugins" element={<PluginsPage />} />
          <Route path="tools" element={<ToolsPage />} />
          <Route path="audio" element={<AudioPanel />} />
          <Route path="audio-test" element={<AudioTestPage />} />
          <Route path="audio-workstation" element={<AudioWorkstationPage />} />
          {/* 旧路由重定向兼容 */}
          <Route path="voice-workstation" element={<Navigate to="/audio-workstation" replace />} />
          <Route path="compose" element={<Navigate to="/audio-workstation?tab=compose" replace />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="memory-agent" element={<MemoryAgentPage />} />
          <Route path="vector-data" element={<VectorDataPage />} />
          <Route path="live" element={<LivePage />} />
          <Route path="live/split" element={<LiveSplitPage />} />
        </Route>
        <Route path="/live/split/avatar" element={<AvatarSource />} />
        <Route path="/live/split/danmaku" element={<DanmakuSource />} />
        <Route path="/live/split/subtitle" element={<SubtitleSource />} />
        <Route path="/live/split/audio" element={<AudioPanelOBS />} />
        <Route path="/pet" element={<PetPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </ErrorBoundary>
  );
}

export default App;
