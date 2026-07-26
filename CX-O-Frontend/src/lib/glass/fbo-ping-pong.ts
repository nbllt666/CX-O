/**
 * fbo-ping-pong.ts — Liquid Glass 双 FBO ping-pong 管理器
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (renderPipeline) +
 *        I1 frontend_glass.pyi (FBOManager class)
 * 用途: 管理 backgroundFBO（背景采样）与 glassFBO（折射+色散+高光合成）的 ping-pong
 *
 * 双 FBO ping-pong（D2 renderPipeline.fboStrategy = double-fbo-ping-pong）:
 *   - backgroundFBO: 每帧通过 drawElement 离屏渲染当前页面背景（30fps，滚动 60fps）
 *   - glassFBO: 执行折射+色散+高光合成
 *   - blitToMainCanvas: 将 glassFBO 结果 blit 到主 canvas
 *
 * GPU 内存（D2 gpuMemoryManagement + C1 memoryLimits）:
 *   - 双 FBO 总显存 ≤ 48MB（由 GPUMemoryManager 断言）
 *
 * 错误码（E1）:
 *   - FE-GLA-003: FBO 创建失败（gl.createFramebuffer 返回 null 或 checkFramebufferStatus 不完整）
 * ============================================================================
 */

import { GPUMemoryManager } from './gpu-memory-manager';

// ============================================================================
// 异常定义（I1 异常契约）
// ============================================================================

/**
 * FBO 帧缓冲对象创建失败异常（I1 FBOCreationError, FE-GLA-003）。
 *
 * 抛出条件: FBOManager.createPingPongFBO 调用 gl.createFramebuffer 返回 null，
 *   或 gl.checkFramebufferStatus 不为 FRAMEBUFFER_COMPLETE。
 * 调用方处理: 捕获后释放已分配资源，降级到 Tier 3，上报错误码 FE-GLA-003。
 */
export class FBOCreationError extends Error {
  readonly errorCode: 'FE-GLA-003';
  readonly fboLabel: string;
  readonly status: number | null;

  constructor(message: string, fboLabel: string, status: number | null = null) {
    super(message);
    this.name = 'FBOCreationError';
    this.errorCode = 'FE-GLA-003';
    this.fboLabel = fboLabel;
    this.status = status;
    Object.setPrototypeOf(this, FBOCreationError.prototype);
  }
}

// ============================================================================
// FBO 管理类型
// ============================================================================

/**
 * FBO 包装对象（含 framebuffer + 颜色附件纹理）。
 */
export interface FBOBundle {
  /** WebGLFramebuffer 对象 */
  framebuffer: WebGLFramebuffer;
  /** 颜色附件纹理 */
  texture: WebGLTexture;
  /** FBO 宽度 */
  width: number;
  /** FBO 高度 */
  height: number;
}

// ============================================================================
// WebGL1 blit shader 源码（WebGL1 无 blitFramebuffer，用 shader 实现）
// ============================================================================

const BLIT_VERT_SRC = `
attribute vec2 aPosition;
attribute vec2 aTexCoord;
varying vec2 vUv;
void main() {
  vUv = aTexCoord;
  gl_Position = vec4(aPosition, 0.0, 1.0);
}
`;

const BLIT_FRAG_SRC = `
precision highp float;
varying vec2 vUv;
uniform sampler2D uTexture;
void main() {
  gl_FragColor = texture2D(uTexture, vUv);
}
`;

// ============================================================================
// FBOManager 类（I1 签名匹配）
// ============================================================================

/**
 * FBO 帧缓冲管理器（I1 FBOManager, merged.md §2.3 双 FBO ping-pong + §2.7 GPU 内存管理）。
 *
 * 管理 backgroundFBO（背景采样）与 glassFBO（折射+色散+高光合成）的 ping-pong。
 * 双 FBO 总显存 ≤ 48MB。
 */
export class FBOManager {
  /** GL 上下文 */
  private gl: WebGLRenderingContext | WebGL2RenderingContext;

  /** 是否为 WebGL2 */
  private isWebGL2: boolean;

  /** GPU 内存管理器引用 */
  private memoryManager: GPUMemoryManager;

  /** backgroundFBO */
  private backgroundFBO: FBOBundle | null = null;

  /** glassFBO */
  private glassFBO: FBOBundle | null = null;

  /** WebGL1 blit shader 程序 */
  private blitProgram: WebGLProgram | null = null;

  /** blit shader 的顶点缓冲 */
  private blitQuadBuffer: WebGLBuffer | null = null;

  /** blit shader uniform location */
  private blitTextureLocation: WebGLUniformLocation | null = null;

  constructor(
    gl: WebGLRenderingContext | WebGL2RenderingContext,
    memoryManager: GPUMemoryManager,
  ) {
    this.gl = gl;
    this.isWebGL2 = gl instanceof WebGL2RenderingContext;
    this.memoryManager = memoryManager;
  }

  /**
   * 创建 ping-pong 双 FBO（I1 createPingPongFBO）。
   *
   * 创建 backgroundFBO 和 glassFBO，每个 FBO 附加一个 RGBA8 纹理作为颜色附件。
   * 双 FBO 总显存 ≤ 48MB（由 GPUMemoryManager 断言）。
   *
   * @param width FBO 宽度（px）
   * @param height FBO 高度（px）
   * @returns [backgroundFBO, glassFBO] 双 FBO
   * @throws FBOCreationError gl.createFramebuffer 返回 null，或 checkFramebufferStatus 不完整
   */
  createPingPongFBO(width: number, height: number): [FBOBundle, FBOBundle] {
    // 断言双 FBO 内存 ≤ 48MB（C1 memoryLimits.fboMemoryLimit）
    this.memoryManager.assertFboMemoryLimit(width, height);

    // 创建 backgroundFBO
    this.backgroundFBO = this.createSingleFBO(width, height, 'backgroundFBO');

    // 创建 glassFBO
    this.glassFBO = this.createSingleFBO(width, height, 'glassFBO');

    // WebGL1 下初始化 blit shader
    if (!this.isWebGL2) {
      this.initBlitShader();
    }

    return [this.backgroundFBO, this.glassFBO];
  }

  /**
   * 创建单个 FBO（含 framebuffer + 纹理附件）。
   *
   * @param width FBO 宽度
   * @param height FBO 高度
   * @param label FBO 标识（用于错误信息）
   * @returns FBOBundle
   * @throws FBOCreationError 创建失败时抛出
   */
  private createSingleFBO(width: number, height: number, label: string): FBOBundle {
    const gl = this.gl;

    // 创建纹理
    const texture = gl.createTexture();
    if (!texture) {
      throw new FBOCreationError(`Failed to create texture for ${label}`, label);
    }
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // 创建 framebuffer
    const framebuffer = gl.createFramebuffer();
    if (!framebuffer) {
      gl.deleteTexture(texture);
      throw new FBOCreationError(`Failed to create framebuffer for ${label}`, label);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);

    // 检查 framebuffer 完整性
    const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
    if (status !== gl.FRAMEBUFFER_COMPLETE) {
      gl.deleteFramebuffer(framebuffer);
      gl.deleteTexture(texture);
      throw new FBOCreationError(
        `Framebuffer ${label} is not complete: status ${status}`,
        label,
        status,
      );
    }

    // 解绑
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.bindTexture(gl.TEXTURE_2D, null);

    return { framebuffer, texture, width, height };
  }

  /**
   * FBO 间 blit 拷贝（I1 blit）。
   *
   * WebGL2: 使用 gl.blitFramebuffer
   * WebGL1: 使用 blit shader + 全屏 quad 渲染
   *
   * @param srcFBO 源 FBO
   * @param dstFBO 目标 FBO
   * @param mask 拷贝 mask（如 COLOR_BUFFER_BIT）
   * @throws FBOCreationError srcFBO 或 dstFBO 已被 deleteFBO 释放时抛出
   */
  blit(srcFBO: FBOBundle, dstFBO: FBOBundle, mask: number): void {
    if (!srcFBO.framebuffer || !dstFBO.framebuffer) {
      throw new FBOCreationError('Cannot blit: srcFBO or dstFBO has been deleted', 'blit');
    }

    const gl = this.gl;

    if (this.isWebGL2) {
      // WebGL2: 使用 blitFramebuffer
      const gl2 = gl as WebGL2RenderingContext;
      gl.bindFramebuffer(gl2.READ_FRAMEBUFFER, srcFBO.framebuffer);
      gl.bindFramebuffer(gl2.DRAW_FRAMEBUFFER, dstFBO.framebuffer);
      gl2.blitFramebuffer(
        0, 0, srcFBO.width, srcFBO.height,
        0, 0, dstFBO.width, dstFBO.height,
        mask,
        gl.LINEAR,
      );
      gl.bindFramebuffer(gl2.READ_FRAMEBUFFER, null);
      gl.bindFramebuffer(gl2.DRAW_FRAMEBUFFER, null);
    } else {
      // WebGL1: 使用 blit shader 渲染
      this.blitViaShader(srcFBO, dstFBO);
    }
  }

  /**
   * 将 glassFBO 结果 blit 到主 canvas（D2 renderPipeline.blitToMainCanvas = true）。
   *
   * @param glassFBO 玻璃 FBO
   */
  blitToMainCanvas(glassFBO: FBOBundle): void {
    const gl = this.gl;

    // 绑定到主 canvas 的默认 framebuffer
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);

    // 使用 blit shader 将 glassFBO 纹理渲染到主 canvas
    if (this.isWebGL2) {
      // WebGL2: 先 blit 到一个临时 FBO，再渲染到主 canvas
      // 简化：直接用 shader 渲染纹理到主 canvas
      this.renderTextureToCurrentTarget(glassFBO.texture, glassFBO.width, glassFBO.height);
    } else {
      this.renderTextureToCurrentTarget(glassFBO.texture, glassFBO.width, glassFBO.height);
    }
  }

  /**
   * 释放 FBO 资源（I1 deleteFBO）。
   *
   * 调用 gl.deleteFramebuffer 和 gl.deleteTexture 显式释放。
   *
   * @param fbo 待释放的 FBO
   */
  deleteFBO(fbo: FBOBundle): void {
    const gl = this.gl;
    gl.deleteFramebuffer(fbo.framebuffer);
    gl.deleteTexture(fbo.texture);
    fbo.framebuffer = null as unknown as WebGLFramebuffer;
    fbo.texture = null as unknown as WebGLTexture;
  }

  /**
   * 释放所有 FBO 资源和 blit shader。
   */
  dispose(): void {
    if (this.backgroundFBO) {
      this.deleteFBO(this.backgroundFBO);
      this.backgroundFBO = null;
    }
    if (this.glassFBO) {
      this.deleteFBO(this.glassFBO);
      this.glassFBO = null;
    }
    if (this.blitProgram) {
      this.gl.deleteProgram(this.blitProgram);
      this.blitProgram = null;
    }
    if (this.blitQuadBuffer) {
      this.gl.deleteBuffer(this.blitQuadBuffer);
      this.blitQuadBuffer = null;
    }
  }

  /**
   * 获取 backgroundFBO。
   */
  getBackgroundFBO(): FBOBundle | null {
    return this.backgroundFBO;
  }

  /**
   * 获取 glassFBO。
   */
  getGlassFBO(): FBOBundle | null {
    return this.glassFBO;
  }

  // ============================================================================
  // WebGL1 blit shader 内部实现
  // ============================================================================

  /**
   * 初始化 WebGL1 blit shader（简单的纹理拷贝 shader）。
   */
  private initBlitShader(): void {
    const gl = this.gl;

    // 编译 vertex shader
    const vertShader = gl.createShader(gl.VERTEX_SHADER);
    if (!vertShader) return;
    gl.shaderSource(vertShader, BLIT_VERT_SRC);
    gl.compileShader(vertShader);

    // 编译 fragment shader
    const fragShader = gl.createShader(gl.FRAGMENT_SHADER);
    if (!fragShader) {
      gl.deleteShader(vertShader);
      return;
    }
    gl.shaderSource(fragShader, BLIT_FRAG_SRC);
    gl.compileShader(fragShader);

    // 链接程序
    const program = gl.createProgram();
    if (!program) {
      gl.deleteShader(vertShader);
      gl.deleteShader(fragShader);
      return;
    }
    gl.attachShader(program, vertShader);
    gl.attachShader(program, fragShader);
    gl.linkProgram(program);
    gl.deleteShader(vertShader);
    gl.deleteShader(fragShader);

    this.blitProgram = program;

    // 创建全屏 quad 顶点缓冲
    this.blitQuadBuffer = gl.createBuffer();
    if (this.blitQuadBuffer) {
      gl.bindBuffer(gl.ARRAY_BUFFER, this.blitQuadBuffer);
      // 两个三角形组成全屏 quad：位置 + 纹理坐标
      const vertices = new Float32Array([
        -1, -1, 0, 0,
        1, -1, 1, 0,
        -1, 1, 0, 1,
        -1, 1, 0, 1,
        1, -1, 1, 0,
        1, 1, 1, 1,
      ]);
      gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);
    }

    // 获取 uniform location
    this.blitTextureLocation = gl.getUniformLocation(program, 'uTexture');
  }

  /**
   * 使用 blit shader 将源 FBO 纹理渲染到目标 FBO（WebGL1 路径）。
   */
  private blitViaShader(srcFBO: FBOBundle, dstFBO: FBOBundle): void {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, dstFBO.framebuffer);
    this.renderTextureToCurrentTarget(srcFBO.texture, srcFBO.width, srcFBO.height);
  }

  /**
   * 使用 blit shader 将纹理渲染到当前绑定的 framebuffer。
   */
  private renderTextureToCurrentTarget(texture: WebGLTexture, width: number, height: number): void {
    if (!this.blitProgram || !this.blitQuadBuffer) {
      // 如果没有 blit shader（WebGL2 也不需要），直接用 WebGL2 的 blitFramebuffer
      // 或者初始化 blit shader（如果尚未初始化）
      if (!this.blitProgram) {
        this.initBlitShader();
      }
      if (!this.blitProgram || !this.blitQuadBuffer) return;
    }

    const gl = this.gl;
    gl.viewport(0, 0, width, height);
    gl.useProgram(this.blitProgram);

    // 绑定纹理
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    if (this.blitTextureLocation) {
      gl.uniform1i(this.blitTextureLocation, 0);
    }

    // 绑定顶点缓冲
    gl.bindBuffer(gl.ARRAY_BUFFER, this.blitQuadBuffer);
    const posLoc = gl.getAttribLocation(this.blitProgram, 'aPosition');
    const texLoc = gl.getAttribLocation(this.blitProgram, 'aTexCoord');
    if (posLoc >= 0) {
      gl.enableVertexAttribArray(posLoc);
      gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 16, 0);
    }
    if (texLoc >= 0) {
      gl.enableVertexAttribArray(texLoc);
      gl.vertexAttribPointer(texLoc, 2, gl.FLOAT, false, 16, 8);
    }

    // 绘制全屏 quad
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }
}
