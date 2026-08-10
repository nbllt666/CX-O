/**
 * 音频源页（SubTask 8.2，管理窗内路由 audio-source + 顶层 OBS 路由 /source/audio-source）
 *
 * 复用既有音频渲染/数据链路：直接渲染 AudioPanelPage（麦克风采集、TTS 音量、增益、
 * 回声消除、Live WS 同步）。行为对齐 CX-O-Frontend AudioPanelOBS（AudioPanel + 透明背景）。
 * 自包含 OBS 浏览器源：透明背景、全屏画布，无管理布局依赖。
 */
import { useEffect } from 'react';
import AudioPanelPage from './AudioPanelPage';

export default function AudioSourcePage() {
  useEffect(() => {
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = '';
      document.documentElement.style.background = '';
    };
  }, []);

  return (
    <div
      className="h-screen w-screen overflow-y-auto"
      style={{ backgroundColor: 'transparent' }}
    >
      <AudioPanelPage />
    </div>
  );
}
