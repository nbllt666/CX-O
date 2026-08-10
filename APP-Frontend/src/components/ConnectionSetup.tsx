/**
 * 连接设置页：后端不可达时的连接检测门。
 *
 * 行为口径对齐 CX-O-Frontend src/components/ConnectionSetup.tsx：
 * - 挂载后自动尝试一次连接；
 * - 表单可修改后端地址 / WS 地址，提交后重新探测 /health；
 * - 成功后写缓存 + localStorage +（Electron 下）IPC 持久化，回调 onConnected。
 *
 * 差异：WS 地址允许留空（由 base.ts 按 http→ws/https→wss 自动推导）；
 * 样式使用本工程设计 token（glass-panel / text-primary 等）。
 */
import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { Link2 } from 'lucide-react';
import {
  DEFAULT_BACKEND_URL,
  getApiBaseUrl,
  setBackendUrl,
  setWsUrl,
  STORAGE_KEYS,
} from '../api/base';

interface ConnectionSetupProps {
  onConnected: () => void;
}

export function ConnectionSetup({ onConnected }: ConnectionSetupProps) {
  const { t } = useTranslation();
  const [backendUrl, setBackendUrlState] = useState(() => getApiBaseUrl());
  const [wsUrl, setWsUrlState] = useState(
    () => localStorage.getItem(STORAGE_KEYS.wsUrl) || '',
  );
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState('');

  const checkConnection = async () => {
    setIsChecking(true);
    setError('');

    try {
      const response = await fetch(`${backendUrl}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000),
      });

      if (response.ok) {
        setBackendUrl(backendUrl);
        if (wsUrl.trim()) {
          setWsUrl(wsUrl.trim());
        }
        onConnected();
      } else {
        setError(t('connection.serverError', { status: response.status }));
      }
    } catch (e) {
      setError(
        t('connection.unreachable', {
          message: e instanceof Error ? e.message : 'Unknown error',
        }),
      );
    } finally {
      setIsChecking(false);
    }
  };

  // 挂载后自动尝试一次（地址来自已解析的缓存链）
  useEffect(() => {
    void checkConnection();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void checkConnection();
  };

  return (
    <div className="app-surface relative flex min-h-screen items-center justify-center overflow-hidden">
      {/* 二次元装饰背景光晕 */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse at 30% 20%, rgba(255, 183, 225, 0.15) 0%, transparent 50%), radial-gradient(ellipse at 70% 80%, rgba(124, 216, 255, 0.12) 0%, transparent 50%)',
        }}
      />
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.34, 1.56, 0.64, 1] }}
        className="glass-panel relative z-10 w-full max-w-md p-8"
      >
        <div className="mb-6 text-center">
          <div className="mb-3 flex justify-center">
            <Link2 className="h-8 w-8 text-primary" />
          </div>
          <h1 className="text-gradient mb-2 text-2xl font-bold">{t('connection.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('connection.subtitle')}</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-2 block text-sm font-medium">{t('connection.backendUrl')}</label>
            <input
              type="url"
              value={backendUrl}
              onChange={(e) => setBackendUrlState(e.target.value)}
              placeholder={DEFAULT_BACKEND_URL}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-4 py-2 backdrop-blur-sm transition-colors focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
              required
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">{t('connection.wsUrl')}</label>
            <input
              type="text"
              value={wsUrl}
              onChange={(e) => setWsUrlState(e.target.value)}
              placeholder="ws://127.0.0.1:8100"
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-4 py-2 backdrop-blur-sm transition-colors focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
            <p className="mt-1 text-xs text-muted-foreground">{t('connection.wsUrlHint')}</p>
          </div>

          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-500">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={isChecking}
            className="w-full rounded-lg bg-primary py-3 font-medium text-primary-foreground transition-opacity duration-fast hover:opacity-85 disabled:opacity-50"
          >
            {isChecking ? t('connection.connecting') : t('connection.connect')}
          </button>
        </form>

        <div className="mt-6 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4 text-xs text-muted-foreground">
          <p className="mb-2 font-medium">{t('connection.defaultTitle')}</p>
          <ul className="space-y-1">
            <li>• {t('connection.defaultBackend', { url: DEFAULT_BACKEND_URL })}</li>
            <li>• {t('connection.defaultWs')}</li>
          </ul>
        </div>
      </motion.div>
    </div>
  );
}

export default ConnectionSetup;
