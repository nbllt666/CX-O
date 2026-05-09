import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8100',
        ws: true,
      },
      '/control': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
      },
      '/voice-station': {
        target: 'http://127.0.0.1:8200',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/voice-station/, ''),
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
          ui: ['lucide-react', 'clsx', 'tailwind-merge'],
          state: ['zustand'],
        },
      },
    },
    chunkSizeWarningLimit: 500,
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom', 'zustand', 'lucide-react'],
  },
});
