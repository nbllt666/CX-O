/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 模型工作站独立前端（CXO-ModelStation/frontend）
// - dev 端口 3300（spec 冻结）
// - /api 代理到 ModelStation 后端 8300
// - build 产物 dist/ 由后端 _mount_frontend 自动静态托管
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3300,
    proxy: {
      "/api": "http://127.0.0.1:8300",
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
});
