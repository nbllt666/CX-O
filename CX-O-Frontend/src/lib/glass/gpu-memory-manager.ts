/**
 * gpu-memory-manager.ts — Liquid Glass GPU 内存管理器
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (gpuMemoryManagement) +
 *        C1 frontend_glass_config.schema.json (memoryLimits + performanceMonitor) +
 *        I1 frontend_glass.pyi (ContextLossStatus)
 * 用途: 双 FBO 内存 ≤ 48MB 断言 + Live2D LRU 缓存上限 3 + cleanup + 60s 上下文丢失探测
 *
 * GPU 内存管理（D2 gpuMemoryManagement + C1 memoryLimits）:
 *   - normalLUT: precomputed（法线 LUT 预计算，256x256）
 *   - refractionSampling: textureLod（折射采样优化）
 *   - specularPrecision: half-float（高光半精度浮点）
 *   - live2DCache: { type: LRU, maxModels: 3, releaseOnSwitch: gl.deleteTexture() }
 *   - contextLossDetection: { interval: 60s, method: gl.getError(), fallback: tier3 }
 *
 * 内存上限（C1 memoryLimits）:
 *   - fboMemoryLimit: 48 MB（双 FBO ping-pong 总显存上限，强制断言）
 *   - live2dCacheLimit: maxModels: 3
 *   - normalLUTSize: 256x256
 *
 * 错误码（E1）:
 *   - FE-GLA-002: GPU 上下文丢失（60s 探测或 webglcontextlost 事件）
 * ============================================================================
 */

import type { GlassTier } from './tier-detector';

// ============================================================================
// 类型定义（I1 TypedDict 对应）
// ============================================================================

/**
 * GPU 上下文丢失状态（I1 ContextLossStatus）。
 */
export interface ContextLossStatus {
  /** 上下文是否已丢失 */
  isLost: boolean;
  /** 上次检测时间戳（ms） */
  lastCheckTime: number;
  /** 恢复后降级到的 tier */
  recoveredTier: GlassTier | null;
}

/**
 * Live2D 模型缓存条目。
 */
interface Live2DCacheEntry {
  /** 模型 ID */
  modelId: string;
  /** 纹理对象 */
  texture: WebGLTexture;
  /** 估算内存占用（MB） */
  memoryMB: number;
  /** 最后访问时间戳（ms） */
  lastAccessed: number;
}

// ============================================================================
// 常量定义（C1 配置驱动，禁止硬编码 magic number）
// ============================================================================

/** 双 FBO 总显存上限 MB（C1 memoryLimits.fboMemoryLimit.mb = 48） */
const FBO_MEMORY_LIMIT_MB = 48;

/** Live2D LRU 缓存上限（C1 memoryLimits.live2dCacheLimit.maxModels = 3） */
const LIVE2D_CACHE_MAX_MODELS = 3;

/** 法线 LUT 尺寸（C1 memoryLimits.normalLUTSize = 256x256） */
const NORMAL_LUT_WIDTH = 256;
const NORMAL_LUT_HEIGHT = 256;

/** 上下文丢失探测间隔 ms（C1 performanceMonitor.performanceMonitorInterval.seconds = 60） */
const CONTEXT_LOSS_PROBE_INTERVAL_MS = 60_000;

/** 每像素字节数（RGBA8 = 4 bytes） */
const BYTES_PER_PIXEL = 4;

/** MB 转换常数 */
const BYTES_PER_MB = 1024 * 1024;

// ============================================================================
// 异常定义（I1 异常契约）
// ============================================================================

/**
 * GPU 上下文丢失异常（I1 GPUContextLossError, FE-GLA-002）。
 *
 * 抛出条件: gl.getError() 返回 CONTEXT_LOST_WEBGL，或扩展 WEBGL_lose_context 触发 context loss 事件。
 * 调用方处理: 捕获后触发 TierDegradeError 降级流程，释放 GPU 资源，上报错误码 FE-GLA-002。
 */
export class GPUContextLossError extends Error {
  readonly errorCode: 'FE-GLA-002';
  readonly lastCheckTime: number;

  constructor(message: string, lastCheckTime: number) {
    super(message);
    this.name = 'GPUContextLossError';
    this.errorCode = 'FE-GLA-002';
    this.lastCheckTime = lastCheckTime;
    Object.setPrototypeOf(this, GPUContextLossError.prototype);
  }
}

// ============================================================================
// GPUMemoryManager 类
// ============================================================================

/**
 * GPU 内存管理器（D2 gpuMemoryManagement + C1 memoryLimits）。
 *
 * 职责:
 *   - 双 FBO 内存 ≤ 48MB 强制断言（超限触发降级）
 *   - 角色 Live2D 纹理 LRU 缓存上限 3（切换时 gl.deleteTexture() 释放）
 *   - cleanup: gl.deleteFramebuffer / gl.deleteProgram / gl.deleteTexture
 *   - 每 60s gl.getError() 探测上下文丢失
 */
export class GPUMemoryManager {
  /** GL 上下文 */
  private gl: WebGLRenderingContext | WebGL2RenderingContext;

  /** Live2D LRU 缓存 */
  private live2DCache: Map<string, Live2DCacheEntry> = new Map();

  /** 已注册的 FBO 内存占用（MB） */
  private fboMemoryMB = 0;

  /** 法线 LUT 纹理内存占用（MB） */
  private normalLUTMemoryMB = 0;

  /** 上下文丢失状态 */
  private contextLossStatus: ContextLossStatus = {
    isLost: false,
    lastCheckTime: 0,
    recoveredTier: null,
  };

  /** 上下文丢失探测定时器 */
  private probeHandle: ReturnType<typeof setInterval> | null = null;

  /** 上下文丢失回调 */
  private contextLossCallback: (() => void) | null = null;

  constructor(gl: WebGLRenderingContext | WebGL2RenderingContext) {
    this.gl = gl;
    // 计算法线 LUT 内存占用
    this.normalLUTMemoryMB = this.calculateTextureMemoryMB(NORMAL_LUT_WIDTH, NORMAL_LUT_HEIGHT);
  }

  /**
   * 启动上下文丢失探测（每 60s gl.getError()）。
   *
   * D2 gpuMemoryManagement.contextLossDetection:
   *   - interval: 60s
   *   - method: gl.getError()
   *   - fallback: tier3
   *
   * @param onContextLoss 上下文丢失时的回调
   */
  startContextLossProbe(onContextLoss: () => void): void {
    this.contextLossCallback = onContextLoss;
    this.contextLossStatus.lastCheckTime = performance.now();

    this.probeHandle = setInterval(() => {
      this.probeContextLoss();
    }, CONTEXT_LOSS_PROBE_INTERVAL_MS);
  }

  /**
   * 停止上下文丢失探测。
   */
  stopContextLossProbe(): void {
    if (this.probeHandle !== null) {
      clearInterval(this.probeHandle);
      this.probeHandle = null;
    }
  }

  /**
   * 手动探测上下文丢失（gl.getError()）。
   *
   * D2 contextLossDetection.method = "gl.getError()"。
   * 如果 gl.getError() 返回 CONTEXT_LOST_WEBGL，标记上下文丢失并触发回调。
   */
  probeContextLoss(): boolean {
    this.contextLossStatus.lastCheckTime = performance.now();

    // gl.isContextLost() 是更可靠的上下文丢失检测方式
    if (this.gl.isContextLost()) {
      this.contextLossStatus.isLost = true;
      this.contextLossStatus.recoveredTier = null;
      if (this.contextLossCallback) {
        this.contextLossCallback();
      }
      return true;
    }

    // gl.getError() 补充检测（D2 contextLossDetection.method）
    const error = this.gl.getError();
    if (error === this.gl.CONTEXT_LOST_WEBGL) {
      this.contextLossStatus.isLost = true;
      this.contextLossStatus.recoveredTier = null;
      if (this.contextLossCallback) {
        this.contextLossCallback();
      }
      return true;
    }

    return false;
  }

  /**
   * 获取 GPU 上下文丢失状态（I1 ContextLossStatus）。
   *
   * @returns 上下文丢失状态
   */
  getContextLossStatus(): ContextLossStatus {
    return { ...this.contextLossStatus };
  }

  /**
   * 标记上下文已恢复，记录恢复后的 tier。
   *
   * @param recoveredTier 恢复后降级到的 tier
   */
  markContextRecovered(recoveredTier: GlassTier): void {
    this.contextLossStatus.isLost = false;
    this.contextLossStatus.recoveredTier = recoveredTier;
  }

  /**
   * 计算纹理内存占用（MB）。
   *
   * @param width 纹理宽度
   * @param height 纹理高度
   * @returns 内存占用 MB
   */
  private calculateTextureMemoryMB(width: number, height: number): number {
    const bytes = width * height * BYTES_PER_PIXEL;
    return bytes / BYTES_PER_MB;
  }

  /**
   * 计算双 FBO 内存占用（MB）。
   *
   * 双 FBO ping-pong（D2 renderPipeline.fboStrategy = double-fbo-ping-pong）:
   *   - backgroundFBO: width * height * 4 bytes
   *   - glassFBO: width * height * 4 bytes
   *
   * @param width FBO 宽度
   * @param height FBO 高度
   * @returns 双 FBO 总内存占用 MB
   */
  calculateDoubleFboMemoryMB(width: number, height: number): number {
    const singleFboBytes = width * height * BYTES_PER_PIXEL;
    const doubleFboBytes = singleFboBytes * 2;
    return doubleFboBytes / BYTES_PER_MB;
  }

  /**
   * 断言双 FBO 内存 ≤ 48MB（强制断言，超限触发降级）。
   *
   * C1 memoryLimits.fboMemoryLimit.mb = 48。
   * 闭合判据 §4: GPU 内存 ≤ 48MB（强制断言，超限触发降级）。
   *
   * @param width FBO 宽度
   * @param height FBO 高度
   * @returns [isWithinLimit, memoryMB, limitMB]
   * @throws Error 如果双 FBO 内存超限
   */
  assertFboMemoryLimit(width: number, height: number): { isWithinLimit: boolean; memoryMB: number; limitMB: number } {
    const fboMemory = this.calculateDoubleFboMemoryMB(width, height);
    this.fboMemoryMB = fboMemory;

    const totalMemory = fboMemory + this.normalLUTMemoryMB;
    const isWithinLimit = totalMemory <= FBO_MEMORY_LIMIT_MB;

    if (!isWithinLimit) {
      throw new Error(
        `GPU memory limit exceeded: FBO ${fboMemory.toFixed(2)}MB + normalLUT ${this.normalLUTMemoryMB.toFixed(2)}MB = ${totalMemory.toFixed(2)}MB > ${FBO_MEMORY_LIMIT_MB}MB limit`,
      );
    }

    return { isWithinLimit, memoryMB: totalMemory, limitMB: FBO_MEMORY_LIMIT_MB };
  }

  /**
   * 获取当前 GPU 总显存占用（MB）。
   *
   * 包括：双 FBO + 法线 LUT + Live2D 缓存纹理。
   *
   * @returns GPU 显存占用 MB
   */
  getGpuMemoryUsageMB(): number {
    let total = this.fboMemoryMB + this.normalLUTMemoryMB;
    for (const entry of this.live2DCache.values()) {
      total += entry.memoryMB;
    }
    return total;
  }

  // ============================================================================
  // Live2D LRU 缓存管理（D2 gpuMemoryManagement.live2DCache）
  // ============================================================================

  /**
   * 添加 Live2D 模型纹理到 LRU 缓存。
   *
   * D2 live2DCache: { type: LRU, maxModels: 3, releaseOnSwitch: gl.deleteTexture() }
   * C1 live2dCacheLimit: { maxModels: 3 }
   *
   * 如果缓存已满，淘汰最近最少使用的模型（LRU），调用 gl.deleteTexture() 释放。
   *
   * @param modelId 模型 ID
   * @param texture WebGL 纹理对象
   * @param textureWidth 纹理宽度
   * @param textureHeight 纹理高度
   */
  addLive2DModel(
    modelId: string,
    texture: WebGLTexture,
    textureWidth: number,
    textureHeight: number,
  ): void {
    // 如果模型已在缓存中，先移除旧条目
    if (this.live2DCache.has(modelId)) {
      const oldEntry = this.live2DCache.get(modelId);
      if (oldEntry) {
        this.gl.deleteTexture(oldEntry.texture);
      }
      this.live2DCache.delete(modelId);
    }

    // LRU 淘汰：缓存已满时淘汰最旧条目
    while (this.live2DCache.size >= LIVE2D_CACHE_MAX_MODELS) {
      this.evictOldestLive2D();
    }

    // 添加新条目
    const memoryMB = this.calculateTextureMemoryMB(textureWidth, textureHeight);
    this.live2DCache.set(modelId, {
      modelId,
      texture,
      memoryMB,
      lastAccessed: performance.now(),
    });
  }

  /**
   * 访问 Live2D 模型（更新 LRU 时间戳）。
   *
   * @param modelId 模型 ID
   * @returns 纹理对象，如果未找到返回 null
   */
  accessLive2DModel(modelId: string): WebGLTexture | null {
    const entry = this.live2DCache.get(modelId);
    if (!entry) return null;
    entry.lastAccessed = performance.now();
    return entry.texture;
  }

  /**
   * LRU 淘汰最旧的 Live2D 模型。
   * 调用 gl.deleteTexture() 显式释放（D2 live2DCache.releaseOnSwitch）。
   */
  private evictOldestLive2D(): void {
    let oldestKey: string | null = null;
    let oldestTime = Infinity;

    for (const [key, entry] of this.live2DCache) {
      if (entry.lastAccessed < oldestTime) {
        oldestTime = entry.lastAccessed;
        oldestKey = key;
      }
    }

    if (oldestKey !== null) {
      const entry = this.live2DCache.get(oldestKey);
      if (entry) {
        this.gl.deleteTexture(entry.texture);
      }
      this.live2DCache.delete(oldestKey);
    }
  }

  /**
   * 切换 Live2D 模型时释放旧模型（D2 live2DCache.releaseOnSwitch = gl.deleteTexture()）。
   *
   * @param modelId 要释放的模型 ID
   */
  releaseLive2DModel(modelId: string): void {
    const entry = this.live2DCache.get(modelId);
    if (entry) {
      this.gl.deleteTexture(entry.texture);
      this.live2DCache.delete(modelId);
    }
  }

  /**
   * 获取 Live2D 缓存当前模型数。
   */
  getLive2DCacheSize(): number {
    return this.live2DCache.size;
  }

  // ============================================================================
  // Cleanup（D2 gpuMemoryManagement + I1 GlassRenderer.dispose）
  // ============================================================================

  /**
   * 释放所有 GPU 资源。
   *
   * 调用 gl.deleteFramebuffer / gl.deleteProgram / gl.deleteTexture 显式释放。
   * D2 gpuMemoryManagement 约束: 页面卸载时 useEffect cleanup 必须调用本方法。
   *
   * @param framebuffers 待释放的 FBO 列表
   * @param programs 待释放的着色器程序列表
   * @param textures 待释放的纹理列表
   */
  cleanup(
    framebuffers: WebGLFramebuffer[],
    programs: WebGLProgram[],
    textures: WebGLTexture[],
  ): void {
    // 停止上下文丢失探测
    this.stopContextLossProbe();

    // 释放 FBO
    for (const fbo of framebuffers) {
      this.gl.deleteFramebuffer(fbo);
    }

    // 释放着色器程序
    for (const program of programs) {
      this.gl.deleteProgram(program);
    }

    // 释放纹理
    for (const texture of textures) {
      this.gl.deleteTexture(texture);
    }

    // 释放 Live2D 缓存中的纹理
    for (const entry of this.live2DCache.values()) {
      this.gl.deleteTexture(entry.texture);
    }
    this.live2DCache.clear();

    // 重置内存计数
    this.fboMemoryMB = 0;
  }
}
