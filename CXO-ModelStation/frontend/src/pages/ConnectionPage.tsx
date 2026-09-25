/*
 * 连接设置页：展示/修改后端地址与数据根，展示桌面运行时信息。
 *
 * 约束（spec「后端未启动」场景）：
 * - 挂载时只做一次健康检查，不做轮询（失败请求风暴防护）；
 * - 后端不可达时给出明确引导（start.bat 或改地址）；
 * - 浏览器（非 Electron）环境优雅降级：数据根与生命周期动作只读提示。
 */
import { useCallback, useEffect, useState } from "react";
import { NoticeBar } from "../components/ui";
import {
  BACKEND_START_HINT,
  DEFAULT_DATA_ROOT_HINT,
  checkBackend,
  defaultConfig,
  getDesktopBridge,
  isDesktopRuntime,
  isLocalBaseUrl,
  loadConfig,
  saveConfig,
  type AppConfig,
  type BackendStatus,
  type DesktopInfo,
} from "../desktop";

function toMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function ConnectionPage() {
  const desktop = isDesktopRuntime();
  const [info, setInfo] = useState<DesktopInfo | null>(null);
  const [config, setConfig] = useState<AppConfig>(defaultConfig);
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runCheck = useCallback(async (baseUrl: string) => {
    setChecking(true);
    try {
      setStatus(await checkBackend(baseUrl));
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      let loaded = await loadConfig();
      const bridge = getDesktopBridge();
      let desktopInfo: DesktopInfo | null = null;
      if (bridge) {
        try {
          desktopInfo = await bridge.getInfo();
        } catch {
          desktopInfo = null;
        }
      }
      // 桌面态：本机后端可能因默认端口被占用发生顺延，界面与检测都以主进程上报的实际 base 为准
      if (desktopInfo && isLocalBaseUrl(loaded.backendBaseUrl)) {
        loaded = { ...loaded, backendBaseUrl: desktopInfo.backendBaseUrl };
      }
      if (cancelled) return;
      setConfig(loaded);
      setInfo(desktopInfo);
      setReady(true);
      // 挂载仅检查一次（不轮询）
      const checked = await checkBackend(loaded.backendBaseUrl);
      if (!cancelled) setStatus(checked);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await saveConfig(config);
      setConfig(saved);
      setNotice(
        desktop
          ? "配置已保存到 Electron userData；修改数据根或后端地址后建议点击「重启后端」生效。"
          : "配置已保存到浏览器 localStorage（浏览器态不影响 Electron 桌面配置）。",
      );
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const handleRestart = async () => {
    const bridge = getDesktopBridge();
    if (!bridge) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await bridge.restartBackend();
      setNotice(result.message);
      if (result.status) setStatus(result.status);
      else await runCheck(config.backendBaseUrl);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    const bridge = getDesktopBridge();
    if (!bridge) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await bridge.stopBackend();
      setNotice(result.message);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <header className="page-header">
        <h2>连接设置</h2>
        <p>配置后端连接地址与数据根；桌面态可重启/停止由应用托管的后端进程。</p>
      </header>

      <section className="card section-gap">
        <div className="card-title">运行环境</div>
        {desktop && info ? (
          <div className="form-grid">
            <div className="field">
              <label>运行形态</label>
              <input
                readOnly
                value={info.layoutMode === "packaged" ? "桌面安装态（packaged）" : "桌面开发态（dev）"}
              />
            </div>
            <div className="field">
              <label>后端实际地址</label>
              <input readOnly className="mono" value={info.backendBaseUrl} />
            </div>
            <div className="field">
              <label>前端本地站点</label>
              <input
                readOnly
                value={info.frontendPort > 0 ? `${info.frontendUrl}（实际端口 ${info.frontendPort}）` : info.frontendUrl}
              />
            </div>
            <div className="field field-full">
              <label>配置文件</label>
              <input readOnly className="mono" value={info.configFilePath} />
            </div>
          </div>
        ) : (
          <p className="hint">
            当前为浏览器形态：仅可配置后端地址（保存到 localStorage）。数据根与后端进程控制需在 Electron
            桌面应用内使用。
          </p>
        )}
      </section>

      <section className="card section-gap">
        <div className="card-title">连接配置</div>
        <div className="form-grid">
          <div className="field field-full">
            <label htmlFor="backend-url">后端地址</label>
            <input
              id="backend-url"
              className="mono"
              value={config.backendBaseUrl}
              onChange={(e) => setConfig({ ...config, backendBaseUrl: e.target.value })}
              placeholder="http://127.0.0.1:8300"
            />
          </div>
          <div className="field field-full">
            <label htmlFor="data-root">数据根</label>
            <input
              id="data-root"
              className="mono"
              value={config.dataRoot}
              readOnly={!desktop}
              onChange={(e) => setConfig({ ...config, dataRoot: e.target.value })}
              placeholder={desktop ? DEFAULT_DATA_ROOT_HINT : `（桌面态默认 ${DEFAULT_DATA_ROOT_HINT}）`}
            />
          </div>
        </div>
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!ready || checking}
            onClick={() => void runCheck(config.backendBaseUrl)}
          >
            {checking ? "检测中…" : "检测连接"}
          </button>
          <button type="button" className="btn" disabled={!ready || busy} onClick={() => void handleSave()}>
            保存配置
          </button>
          {desktop ? (
            <>
              <button type="button" className="btn" disabled={busy} onClick={() => void handleRestart()}>
                重启后端
              </button>
              <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void handleStop()}>
                停止后端
              </button>
            </>
          ) : null}
        </div>
      </section>

      <section className="card section-gap">
        <div className="card-title">后端状态</div>
        {status === null ? (
          <p className="hint">尚未检测。</p>
        ) : status.healthy ? (
          <p className="notice-bar notice-success" role="status">
            后端可达且健康：{status.baseUrl}
          </p>
        ) : (
          <div className="error-bar" role="alert">
            <span>
              后端不可达（{status.baseUrl}）：{status.detail ?? BACKEND_START_HINT}
            </span>
          </div>
        )}
        {status ? (
          <p className="hint">
            最近检测时间：{new Date(status.checkedAt).toLocaleTimeString()}（仅手动/进入页面时检测，不自动轮询）
          </p>
        ) : null}
      </section>

      <NoticeBar message={notice} variant="success" />
      {error ? (
        <div className="error-bar" role="alert">
          <span>{error}</span>
        </div>
      ) : null}
    </div>
  );
}