import { Link } from 'react-router-dom';

export function LiveSplitPage() {
  const baseUrl = window.location.origin;

  const sources = [
    {
      name: '虚拟形象',
      path: '/live/split/avatar',
      description: '纯 Live2D/VRM 虚拟形象渲染，透明背景，1920×1080',
      icon: (
        <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
      ),
      color: '#a78bfa',
    },
    {
      name: '弹幕层',
      path: '/live/split/danmaku',
      description: '纯弹幕 overlay，透明背景，1920×1080',
      icon: (
        <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
      ),
      color: '#60a5fa',
    },
    {
      name: '字幕层',
      path: '/live/split/subtitle',
      description: '纯 AI 回复字幕显示，透明背景，1920×1080',
      icon: (
        <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
        </svg>
      ),
      color: '#34d399',
    },
    {
      name: '音频控制',
      path: '/live/split/audio',
      description: '音频输入/输出、AEC、TTS 同步、延迟监控',
      icon: (
        <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
        </svg>
      ),
      color: '#fbbf24',
    },
  ];

  return (
    <div className="min-h-screen bg-[var(--color-bg-primary)] p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)] mb-2">拆分模式</h1>
        <p className="text-sm text-[var(--color-text-secondary)] mb-8">
          每个组件作为独立的 OBS 浏览器源使用。每个源的 URL 格式为：<code className="px-2 py-0.5 rounded bg-[var(--color-bg-tertiary)] text-xs">{baseUrl}/live/split/&lt;source&gt;</code>
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {sources.map((source) => (
            <Link
              key={source.path}
              to={source.path}
              className="group block p-6 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)] hover:border-[var(--color-accent)] transition-all duration-200"
            >
              <div className="flex items-start gap-4">
                <div
                  className="flex-shrink-0 w-14 h-14 rounded-xl flex items-center justify-center transition-transform group-hover:scale-110"
                  style={{ backgroundColor: `${source.color}20`, color: source.color }}
                >
                  {source.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-lg font-semibold text-[var(--color-text-primary)] group-hover:text-[var(--color-accent)] transition-colors">
                    {source.name}
                  </h3>
                  <p className="text-sm text-[var(--color-text-secondary)] mt-1">{source.description}</p>
                  {source.path === '/live/split/audio' && (
                    <a href="/audio" target="_blank" rel="noopener noreferrer" className="text-xs text-[var(--color-accent)] hover:underline">
                      在新页面打开 →
                    </a>
                  )}
                  <code className="text-xs text-[var(--color-text-tertiary)] mt-2 block break-all">
                    {baseUrl}{source.path}
                  </code>
                </div>
              </div>
            </Link>
          ))}
        </div>

        <div className="mt-8 p-4 rounded-lg border border-dashed border-[var(--color-border)]">
          <p className="text-sm text-[var(--color-text-secondary)] text-center">
            💡 在 OBS 中添加浏览器源时，设置宽高为 <strong>1920×1080</strong>，并勾选「自定义 CSS」添加 <code className="text-xs px-1 rounded bg-[var(--color-bg-tertiary)]">body &#123; background: transparent; &#125;</code> 以实现透明背景
          </p>
        </div>
      </div>
    </div>
  );
}

export default LiveSplitPage;
