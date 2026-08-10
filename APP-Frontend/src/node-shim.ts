/**
 * 渲染层 Node 内置 require 垫片（生产构建必需）。
 *
 * 背景：渲染层 webPreferences nodeIntegration=false，浏览器上下文没有 `require`。
 * 但部分 CJS 依赖（如 @pixi/utils 的 CJS 构建，经 pixi-live2d-display 等 CJS 消费方引入）
 * 仍会在模块求值时内联执行 `const url = require('url')`。Vite 的 commonjs 插件把 `url`
 * 当作 Node 内置跳过 alias/polyfill 转换，导致生产构建整包在求值时抛
 * `ReferenceError: require is not defined`，所有窗口白屏。
 *
 * 方案：本模块被 main.tsx 作为首个 import 求值，注入一个零依赖的 `require` 垫片，
 * 仅把已知 Node 内置映射到浏览器实现。`url` 用基于 URL 的极简实现（parse/format/resolve），
 * 恰好覆盖 @pixi/utils 的使用；其余内置返回空对象（不抛错）。仅当浏览器未提供 require 时生效。
 *
 * 必须零 import：若这里 import 任何第三方 CJS 包，其自身的 require 会先于本垫片崩溃。
 */
const urlShim = {
  parse(url: string) {
    try {
      return new URL(url);
    } catch {
      return { href: url };
    }
  },
  resolve(from: string, to: string) {
    try {
      return new URL(to, from).href;
    } catch {
      return to;
    }
  },
  format(obj: unknown) {
    const o = obj as { href?: string };
    return o && o.href ? o.href : String(obj ?? '');
  },
};

const shims: Record<string, unknown> = { url: urlShim };

const g = globalThis as Record<string, unknown>;
if (typeof g.require !== 'function') {
  g.require = ((id: string) => shims[id] ?? {}) as unknown as NodeRequire;
}

export {};
