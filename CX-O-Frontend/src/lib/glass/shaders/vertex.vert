/*
 * vertex.vert — Liquid Glass 统一顶点着色器
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (shader) +
 *        I1 frontend_glass.pyi (createGlassShader)
 * 用途: 折射层 / 色散层 / 高光层共用顶点着色器，输出 vUv 与 vScreenPos
 *
 * 设计要点:
 *   - aPosition: quad 顶点位置（NDC 坐标 [-1, 1]）
 *   - aTexCoord: 纹理坐标 [0, 1]
 *   - vUv: 传递给 fragment 的纹理坐标
 *   - vScreenPos: 屏幕空间坐标（用于 Fresnel 视线方向计算）
 *   - uProjection: 正交投影矩阵（全屏 quad 时为单位矩阵）
 *   - 禁止硬编码 magic number：所有可调参数走 C1 配置契约
 * ============================================================================
 */

attribute vec2 aPosition;
attribute vec2 aTexCoord;

uniform mat4 uProjection;

varying vec2 vUv;
varying vec2 vScreenPos;

void main() {
  vUv = aTexCoord;
  vScreenPos = aPosition;
  gl_Position = uProjection * vec4(aPosition, 0.0, 1.0);
}
