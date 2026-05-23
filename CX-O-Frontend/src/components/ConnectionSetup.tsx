import { useState, useEffect } from 'react';

interface ConnectionSetupProps {
  onConnected: () => void;
}

export function ConnectionSetup({ onConnected }: ConnectionSetupProps) {
  const [backendUrl, setBackendUrl] = useState(() => {
    return localStorage.getItem('cxhms-backend-url') || 'http://127.0.0.1:8100';
  });
  const [wsUrl, setWsUrl] = useState(() => {
    return localStorage.getItem('cxhms-ws-url') || 'ws://127.0.0.1:8100';
  });
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    checkConnection();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only probe; URLs come from state/localStorage
  }, []);

  const checkConnection = async () => {
    setIsChecking(true);
    setError('');

    try {
      const response = await fetch(`${backendUrl}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000),
      });

      if (response.ok) {
        localStorage.setItem('cxhms-backend-url', backendUrl);
        localStorage.setItem('cxhms-ws-url', wsUrl);
        onConnected();
      } else {
        setError(`服务器返回错误: ${response.status}`);
      }
    } catch (e) {
      setError(`无法连接到后端服务: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setIsChecking(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    checkConnection();
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg-primary)]">
      <div className="w-full max-w-md p-8 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
        <div className="text-center mb-6">
          <h1 className="text-2xl font-bold mb-2">连接设置</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">
            请输入后端服务地址
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">
              后端地址
            </label>
            <input
              type="url"
              value={backendUrl}
              onChange={(e) => setBackendUrl(e.target.value)}
              placeholder="http://127.0.0.1:8100"
              className="w-full px-4 py-2 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] focus:outline-none focus:border-[var(--color-accent)]"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">
              WebSocket 地址
            </label>
            <input
              type="url"
              value={wsUrl}
              onChange={(e) => setWsUrl(e.target.value)}
              placeholder="ws://127.0.0.1:8100"
              className="w-full px-4 py-2 rounded-lg bg-[var(--color-bg-primary)] border border-[var(--color-border)] focus:outline-none focus:border-[var(--color-accent)]"
              required
            />
          </div>

          {error && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-500 text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={isChecking}
            className="w-full py-3 rounded-lg bg-[var(--color-accent)] text-white font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {isChecking ? '连接中...' : '连接'}
          </button>
        </form>

        <div className="mt-6 p-4 rounded-lg bg-[var(--color-bg-tertiary)] text-xs text-[var(--color-text-secondary)]">
          <p className="font-medium mb-2">默认配置:</p>
          <ul className="space-y-1">
            <li>• 后端地址: http://127.0.0.1:8100</li>
            <li>• WebSocket: ws://127.0.0.1:8100</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
