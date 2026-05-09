import { useState, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { DashboardPage } from './pages/DashboardPage';
import { ChatPage } from './pages/ChatPage';
import { MemoriesPage } from './pages/MemoriesPage';
import { ArchivePage } from './pages/ArchivePage';
import { SettingsPage } from './pages/SettingsPage';
import { AcpPage } from './pages/AcpPage';
import { ToolsPage } from './pages/ToolsPage';
import { AgentsPage } from './pages/AgentsPage';
import { MemoryAgentPage } from './pages/MemoryAgentPage';
import { AudioTestPage } from './pages/AudioTestPage';
import { GraphDataPage } from './pages/GraphDataPage';
import { VectorDataPage } from './pages/VectorDataPage';
import { LivePage } from './pages/LivePage';
import { LiveSplitPage } from './pages/LiveSplitPage';
import { AvatarSource } from './pages/live/AvatarSource';
import { DanmakuSource } from './pages/live/DanmakuSource';
import { SubtitleSource } from './pages/live/SubtitleSource';
import { AudioPanel } from './pages/live/AudioPanel';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ConnectionSetup } from './components/ConnectionSetup';

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    checkBackendConnection();
  }, []);

  const checkBackendConnection = async () => {
    const backendUrl = localStorage.getItem('cxhms-backend-url') || 'http://localhost:8100';

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);

      const response = await fetch(`${backendUrl}/health`, {
        method: 'GET',
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (response.ok) {
        setIsConnected(true);
      } else {
        setIsConnected(false);
      }
    } catch {
      setIsConnected(false);
    } finally {
      setIsChecking(false);
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
          <Route path="tools" element={<ToolsPage />} />
          <Route path="audio" element={<AudioTestPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="memory-agent" element={<MemoryAgentPage />} />
          <Route path="graph-data" element={<GraphDataPage />} />
          <Route path="vector-data" element={<VectorDataPage />} />
          <Route path="live" element={<LivePage />} />
          <Route path="live/split" element={<LiveSplitPage />} />
          <Route path="live/split/avatar" element={<AvatarSource />} />
          <Route path="live/split/danmaku" element={<DanmakuSource />} />
          <Route path="live/split/subtitle" element={<SubtitleSource />} />
          <Route path="live/split/audio" element={<AudioPanel />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}

export default App;
