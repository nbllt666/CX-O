// 首个 import：生产构建下 pixi 等 CJS 依赖会在求值时 require('url')，
// 渲染层无 require，必须先注入垫片，否则整包白屏。
import './node-shim';
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './i18n';
import './styles/globals.css';
import { initBackendUrl } from './api/base';
import { initElectronStorage } from './lib/electronStorage';

/**
 * 启动顺序（Electron 模式下关键）：
 * 1. initElectronStorage：预载 userData 中的持久化状态到内存缓存，
 *    保证 zustand persist 首次同步读取命中 IPC 数据而非空 localStorage；
 * 2. initBackendUrl：按 IPC > localStorage > env > 默认 解析后端地址并缓存，
 *    保证首个 API/WS 调用即指向正确地址。
 * 两者均失败安全（出错静默回退），不阻塞渲染。
 */
async function bootstrap() {
  await initElectronStorage();
  await initBackendUrl();

  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

void bootstrap();
