/**
 * theme-bootstrap.ts — 防闪烁 bootstrap 工具（生成内联脚本字符串）
 * ============================================================================
 * 模块: 模块2 主题层
 * 契约: D3 theme.schema.json (bootstrap) + I2 frontend_theme.pyi (ThemeBootstrap)
 * 错误码: FE-THE-001 (BootstrapInjectionError)
 *
 * 设计要点:
 *   - 生成 ≤1.5KB 内联脚本，SSR 前同步读取 localStorage 设置 data-theme，避免 FOUC
 *   - 脚本注入位置: index.html <head> 第一个子元素（在所有 CSS 之前）
 *   - 执行时机: 同步执行，在 CSS 加载前完成（D3 executionTiming = synchronous-before-css）
 *   - localStorage key: 'cx-o-theme'（与 use-theme-store STORAGE_KEY 一致）
 *   - zustand persist 格式兼容: 解析 {"state":{"theme":"dark"},"version":1}
 *
 * 安全策略:
 *   - index.html 是受保护入口文件，本模块仅导出脚本字符串，不自行注入
 *   - 主线程决定是否注入 index.html（见产出报告说明）
 * ============================================================================
 */

import { Theme } from './use-theme-store';

// ============================================================================
// 常量定义（配置驱动，与 D3 bootstrap 对齐）
// ============================================================================

/** localStorage key（D3 bootstrap.localStorageKey，与 use-theme-store STORAGE_KEY 一致） */
const STORAGE_KEY = 'cx-o-theme';

/** 内联脚本大小上限（字节，D3 bootstrap.inlineScriptSize default = 1536 = 1.5KB） */
const DEFAULT_SCRIPT_SIZE_BUDGET_BYTES = 1536;

/** fallback 主题（D3 bootstrap.fallbackTheme = 'dark'） */
const FALLBACK_THEME: Theme = 'dark';

// ============================================================================
// 异常定义（I2 异常契约，FE-THE-001）
// ============================================================================

/**
 * 主题 bootstrap 脚本注入失败异常（I2 BootstrapInjectionError）。
 *
 * 抛出条件: ThemeBootstrap 生成的脚本大小超过 scriptSizeBudget（默认 1.5KB），
 *   或脚本内容校验失败（含语法错误或安全风险）。
 * 调用方处理: 捕获后降级到默认主题（不注入脚本，接受 FOUC 风险），
 *   上报错误码 FE-THE-001（对应 E1 bootstrap 注入失败，severity=error）。
 */
export class BootstrapInjectionError extends Error {
  readonly errorCode: 'FE-THE-001';
  readonly scriptSize: number;
  readonly budget: number;

  constructor(message: string, scriptSize: number, budget: number) {
    super(message);
    this.name = 'BootstrapInjectionError';
    this.errorCode = 'FE-THE-001';
    this.scriptSize = scriptSize;
    this.budget = budget;
    Object.setPrototypeOf(this, BootstrapInjectionError.prototype);
  }
}

// ============================================================================
// 脚本内容生成（D3 bootstrap.scriptContent 实现）
// ============================================================================

/**
 * 生成 bootstrap 内联脚本内容（不含 <script> 标签）。
 *
 * 脚本逻辑（同步执行，不阻塞首屏渲染）:
 *   1. 同步读取 localStorage 中的主题持久化数据（zustand persist 格式）
 *   2. 反序列化并校验主题值（'dark' | 'light'）
 *   3. 设置 document.documentElement.setAttribute('data-theme', theme)
 *   4. 全部同步执行，在首屏渲染前完成 data-theme 设置
 *
 * @param fallbackTheme - localStorage 无数据或读取失败时使用的 fallback 主题
 * @returns 脚本内容字符串（不含 <script> 标签）
 */
function buildScriptContent(fallbackTheme: Theme): string {
  // 脚本使用 IIFE 封装，同步执行
  // 兼容 zustand persist 格式: {"state":{"theme":"dark"},"version":1}
  // 也兼容裸值格式: "dark"（向后兼容）
  return (
    '(function(){' +
    'try{' +
    "var k='" + STORAGE_KEY + "';" +
    "var f='" + fallbackTheme + "';" +
    'var t=f;' +
    'try{' +
    'var r=localStorage.getItem(k);' +
    'if(r){' +
    'var p=JSON.parse(r);' +
    'var v=p&&p.state&&p.state.theme?p.state.theme:p;' +
    "if(v==='dark'||v==='light'){t=v;}" +
    '}' +
    '}catch(e){}' +
    "document.documentElement.setAttribute('data-theme',t);" +
    '}catch(e){' +
    "document.documentElement.setAttribute('data-theme','" + fallbackTheme + "');" +
    '}' +
    '})();'
  );
}

// ============================================================================
// ThemeBootstrap 函数（I2 签名匹配）
// ============================================================================

/**
 * ThemeBootstrap 选项（I2 ThemeBootstrap options）。
 */
export interface ThemeBootstrapOptions {
  /** 默认主题（localStorage 无数据时使用）。默认 Theme.DARK。 */
  defaultTheme?: Theme;
  /** 脚本大小预算（KB）。默认 1.5KB。超出预算抛出 BootstrapInjectionError。 */
  scriptSizeBudget?: number;
}

/**
 * 函数: ThemeBootstrap — 注入主题 bootstrap 脚本到 index.html（merged.md §1.3 防闪烁）。
 *
 * 注入 1.5KB 内联脚本到 index.html 的 <head> 中，SSR 前同步读取 localStorage 设置
 * data-theme 属性，避免 FOUC（Flash of Unstyled Content）。
 *
 * @param options - bootstrap 选项
 * @returns 注入到 index.html <head> 的内联脚本字符串（含 <script> 标签）
 * @throws BootstrapInjectionError 生成的脚本大小超过 scriptSizeBudget 时抛出
 *
 * TS 签名:
 *   function ThemeBootstrap(options?: { defaultTheme?: Theme; scriptSizeBudget?: number }): string;
 */
export function ThemeBootstrap(options?: ThemeBootstrapOptions): string {
  const defaultTheme = options?.defaultTheme ?? Theme.DARK;
  const scriptSizeBudgetKB = options?.scriptSizeBudget ?? 1.5;
  const scriptSizeBudgetBytes = Math.round(scriptSizeBudgetKB * 1024);

  const scriptContent = buildScriptContent(defaultTheme);
  const scriptTag = '<script>' + scriptContent + '</script>';
  const scriptSize = new Blob([scriptTag]).size;

  if (scriptSize > scriptSizeBudgetBytes) {
    throw new BootstrapInjectionError(
      `Theme bootstrap script size ${scriptSize}B exceeds budget ${scriptSizeBudgetBytes}B`,
      scriptSize,
      scriptSizeBudgetBytes,
    );
  }

  return scriptTag;
}

/**
 * 获取 bootstrap 脚本内容（不含 <script> 标签）。
 * 用于构建时注入或测试校验。
 *
 * @param fallbackTheme - fallback 主题
 * @returns 脚本内容字符串
 */
export function getBootstrapScriptContent(fallbackTheme: Theme = FALLBACK_THEME): string {
  return buildScriptContent(fallbackTheme);
}

/**
 * 校验已注入的 bootstrap 脚本是否符合契约。
 * 用于 GN-004 审查或构建时检查。
 *
 * @param htmlContent - index.html 内容
 * @returns 是否在 <head> 第一个子元素位置注入了合规的 bootstrap 脚本
 */
export function validateBootstrapInjection(htmlContent: string): boolean {
  // 检查 <head> 后紧跟 <script> 且脚本含 data-theme 设置逻辑
  const headScriptPattern = /<head>\s*<script>\s*\(function\(\)\{try\{[^]*data-theme[^]*<\/script>/;
  return headScriptPattern.test(htmlContent);
}

// ============================================================================
// 导出常量（供外部校验引用）
// ============================================================================

/** bootstrap 脚本大小上限（字节） */
export const BOOTSTRAP_SIZE_BUDGET = DEFAULT_SCRIPT_SIZE_BUDGET_BYTES;

/** bootstrap localStorage key */
export const BOOTSTRAP_STORAGE_KEY = STORAGE_KEY;
