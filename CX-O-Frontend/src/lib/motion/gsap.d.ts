/**
 * gsap.d.ts — GSAP 最小类型声明（环境模块声明）
 *
 * 模块: 模块3 动效层（辅助文件）
 *
 * 说明:
 *   GSAP 未在 package.json 中声明（预存在的项目配置问题，见观察项）。
 *   本文件提供 GSAP 的最小类型声明，让 tsc --noEmit 通过类型检查。
 *   运行时 Vite 构建需 gsap 安装后才能通过；动态 import 失败时由
 *   useGsapTimeline / loadGsap 降级为 no-op timeline（符合 I3 接口契约
 *   §GsapTimelineError "GSAP 库未加载" 的异常条件，errorCode=FE-MOT-001）。
 *
 *   完整 GSAP 类型见 @types/gsap 或 gsap 自带类型声明。
 *   本文件仅声明模块3 使用的最小 API 子集。
 */

declare module 'gsap' {
  /** GSAP TweenVars 最小类型——描述动画参数 */
  export interface TweenVars {
    [key: string]: unknown;
    duration?: number;
    ease?: string | unknown;
    x?: number | string;
    y?: number | string;
    opacity?: number;
    scale?: number;
    stagger?: number | unknown;
  }

  /** GSAP Timeline 最小接口——描述 timeline 实例的命令式控制 API */
  export interface Timeline {
    kill(): void;
    clear(): void;
    play(): Timeline;
    pause(): Timeline;
    reverse(): Timeline;
    seek(position: number | string): Timeline;
    to(target: unknown, vars: TweenVars, position?: number | string): Timeline;
    from(target: unknown, vars: TweenVars, position?: number | string): Timeline;
    fromTo(
      target: unknown,
      fromVars: TweenVars,
      toVars: TweenVars,
      position?: number | string,
    ): Timeline;
  }

  /** GSAP TimelineVars 配置 */
  export interface TimelineVars {
    [key: string]: unknown;
    defaults?: TweenVars;
    paused?: boolean;
  }

  /** 创建 timeline */
  export function timeline(vars?: TimelineVars): Timeline;

  /** to 动画 */
  export function to(target: unknown, vars: TweenVars): unknown;

  /** 注册插件 */
  export function registerPlugin(plugin: unknown): void;

  const _default: {
    timeline: typeof timeline;
    to: typeof to;
    registerPlugin: typeof registerPlugin;
  };
  export default _default;
}
