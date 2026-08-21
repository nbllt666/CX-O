/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import electron from 'vite-plugin-electron';
import electronRenderer from 'vite-plugin-electron-renderer';
import { nodePolyfills } from 'vite-plugin-node-polyfills';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));

// ELECTRON=true 时启用 Electron 插件（桌面模式）；否则为纯浏览器开发模式
const enableElectron = process.env.ELECTRON === 'true';

// 渲染层开发服务器端口（已取代原 CX-O-Frontend，前端唯一化后固定 3100）
const DEV_PORT = 3100;

export default defineConfig({
  plugins: [
    react(),
    // @pixi/utils 等 CJS 依赖内部使用 Node 内置 require('url')（parse/format/resolve）。
    // 渲染层 nodeIntegration=false 无 require，commonjs 插件又会把 url 当 Node 内置跳过 alias，
    // 导致生产构建整包在求值时抛 `ReferenceError: require is not defined`、白屏。
    // 用 node-polyfills 为浏览器渲染层注入 url 等内置垫片。
    // 注意：不要在此 include 'punycode'——插件会为 include 的模块生成 resolve.alias，
    // 字符串 find 会同时匹配 'punycode' 与 'punycode/'（rollup 别名语义），
    // 抢在下方自定义别名之前把目录导入指到 CJS 源文件，绕过 optimizeDeps 预打包。
    // 我们自身不导入 Node punycode 内置模块，无需该别名。
    nodePolyfills({ include: ['url', 'path', 'stream', 'util', 'assert'] }),
    ...(enableElectron
      ? [
          electron([
            {
              // 主进程：ESM 输出（package.json type=module），产物 dist-electron/main.js
              entry: 'electron/main.ts',
              vite: {
                build: {
                  outDir: 'dist-electron',
                  rollupOptions: {
                    external: ['electron'],
                  },
                },
              },
            },
            {
              // 预加载：type=module 下插件强制 ESM 输出 → 命名为 .mjs，
              // 对应 main.ts 中 sandbox:false + contextIsolation:true 的组合
              entry: 'electron/preload.ts',
              onstart({ reload }) {
                reload();
              },
              vite: {
                build: {
                  outDir: 'dist-electron',
                  rollupOptions: {
                    external: ['electron'],
                    output: {
                      entryFileNames: '[name].mjs',
                    },
                  },
                },
              },
            },
          ]),
          electronRenderer(),
        ]
      : []),
  ],
  resolve: {
    alias: [
      { find: '@', replacement: path.resolve(__dirname, './src') },
      // node-stdlib-browser/esm/proxy/url.js 用 `import x from 'punycode/'`（目录导入，default import），
      // 但 punycode 是 CJS 无 default export，Vite dev server 因此白屏。
      // 把目录导入重写为裸导入，交给 optimizeDeps 做 CJS→ESM 预打包（自动补 default export）。
      { find: /^punycode\/$/, replacement: 'punycode' },
    ],
    // pixi.js 与 pixi-live2d-display/cubism4 两条导入链会把 @pixi/* 打包成两份实例，
    // 其中一份的 require('url') 未被 node-polyfills 转换，导致渲染层白屏。
    // 强制去重到单一实例，让 node-polyfills 覆盖唯一副本。
    dedupe: ['@pixi/utils', '@pixi/core', '@pixi/display', '@pixi/sprite', '@pixi/loaders', '@pixi/math', '@pixi/constants', '@pixi/settings', '@pixi/ticker', '@pixi/runner', '@pixi/interaction'],
  },
  server: {
    host: true,
    port: DEV_PORT,
    strictPort: true,
    proxy: {
      // 分离部署的后端默认在 8000；生产环境由 config:get-backend-url 提供真实地址
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          ui: ['lucide-react', 'clsx', 'tailwind-merge', 'framer-motion'],
          state: ['zustand'],
        },
      },
    },
    chunkSizeWarningLimit: 500,
  },
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      'zustand',
      'lucide-react',
      // punycode 仅以嵌套副本存在于 node-stdlib-browser/node_modules 下（CJS，无 default export），
      // 从项目根解析不到，裸写 'punycode' 无法命中预打包；必须用 `>` 语法显式包含嵌套副本，
      // 由 esbuild 完成 CJS→ESM 转换（自动补 default export）。
      // qs 同理（url.js 的另一个 CJS 内部依赖，提升在根 node_modules，裸写 'qs' 即可命中）。
      'node-stdlib-browser > punycode',
      'qs',
    ],
  },
  test: {
    globals: false,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    exclude: ['node_modules', 'dist', 'dist-electron', 'release', 'e2e', '**/e2e/**'],
  },
  // 编译期注入仓库根绝对路径（统一正斜杠），供测试读取跨目录配置（如 config/hidden_prompt.yaml）。
  // 由 Node 加载 vite.config 时 __dirname 真实可用，可跨机器/CI 推导，避免硬编码绝对路径。
  define: {
    __CXO_PROJECT_ROOT__: JSON.stringify(path.resolve(__dirname, '../').replace(/\\/g, '/')),
  },
});
