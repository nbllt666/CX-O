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
import { ErrorBoundary } from './components/ErrorBoundary';

function App() {
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
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}

export default App;
