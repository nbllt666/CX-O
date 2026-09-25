/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import electron from "vite-plugin-electron";

// 模型工作站独立前端（CXO-ModelStation/frontend）
// - dev 端口 3300（spec 冻结）：`npm run dev` 保持纯浏览器形态（不启动 Electron）
// - /api、/health 代理到 ModelStation 后端 8300
// - build 产物 dist/ 仍由后端 _mount_frontend 自动静态托管（能力保留）；
//   Electron 桌面形态另有本地静态服务托管同一 dist/（见 electron/staticServer.ts）
//
// Electron 主进程/预加载构建（dist-electron/）仅在以下两种情况启用：
//   - `vite build`（command === 'build'）：产出 dist + dist-electron
//   - `ELECTRON=true vite`（npm run dev:desktop）：dev 形态启动 Electron 窗口
// vitest 与纯浏览器 dev 下不加载该插件，避免测试期/浏览器期被 electron 构建干扰。
export default defineConfig(({ command }) => {
  const isTest = Boolean(process.env.VITEST);
  const enableElectron = !isTest && (command === "build" || process.env.ELECTRON === "true");

  return {
    // 显式 base='/'：避免 vite-plugin-electron 在 build 时把 base 改写为 './'，
    // 保持与既有后端静态托管一致的绝对资源路径语义。
    base: "/",
    plugins: [
      react(),
      ...(enableElectron
        ? [
            electron([
              {
                // 主进程：ESM 输出（package.json type=module）→ dist-electron/main.js
                entry: "electron/main.ts",
                vite: {
                  build: {
                    outDir: "dist-electron",
                    emptyOutDir: true,
                  },
                },
              },
              {
                // 预加载：type=module 下 Electron 要求 ESM 预加载使用 .mjs 扩展名
                entry: "electron/preload.ts",
                onstart({ reload }) {
                  reload();
                },
                vite: {
                  build: {
                    outDir: "dist-electron",
                    emptyOutDir: false,
                    lib: { fileName: () => "[name].mjs" },
                  },
                },
              },
            ]),
          ]
        : []),
    ],
    server: {
      port: 3300,
      proxy: {
        "/api": "http://127.0.0.1:8300",
        "/health": "http://127.0.0.1:8300",
      },
    },
    build: {
      outDir: "dist",
    },
    test: {
      environment: "jsdom",
      // globals: true —— 让 @testing-library/react 注册自动 cleanup（每个测试后卸载）
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});