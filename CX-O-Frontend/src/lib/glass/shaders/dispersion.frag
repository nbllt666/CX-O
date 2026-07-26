/*
 * dispersion.frag — Liquid Glass 色散层 fragment shader
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (shader.fragmentShader.dispersionLayer) +
 *        C1 frontend_glass_config.schema.json (webglUniforms.uDispersionR/G/B)
 * 用途: RGB 通道分别用不同折射系数模拟色差边缘
 *
 * Uniforms（C1 配置驱动，禁止硬编码）:
 *   - uBackgroundTexture: 背景纹理（来自 backgroundFBO）
 *   - uNormalMap: 法线贴图
 *   - uDispersionR: R 通道折射系数，默认 0.075，范围 [0, 0.15]
 *   - uDispersionG: G 通道折射系数，默认 0.080，范围 [0, 0.15]
 *   - uDispersionB: B 通道折射系数，默认 0.085，范围 [0, 0.15]
 *
 * 硬约束（闭合判据 §5）:
 *   - RGB 三通道分别偏移，禁止合并为单值
 *   - R/G/B 默认值 0.075 / 0.080 / 0.085（与 C1 webglUniforms.uDispersionR/G/B 对齐）
 *   - Tier 2 关闭此层（由 GlassRenderer 控制，不编译此 shader）
 * ============================================================================
 */

precision highp float;

varying vec2 vUv;
varying vec2 vScreenPos;

uniform sampler2D uBackgroundTexture;
uniform sampler2D uNormalMap;
uniform float uDispersionR;
uniform float uDispersionG;
uniform float uDispersionB;

void main() {
  // 从法线 LUT 采样 per-pixel 法线
  vec3 normal = texture2D(uNormalMap, vUv).rgb * 2.0 - 1.0;
  normal = normalize(normal);

  // 入射光方向
  vec3 incident = vec3(0.0, 0.0, 1.0);

  // 折射方向基向量
  vec3 refracted = refract(incident, normal, 1.0 / 1.5);
  vec2 baseOffset = refracted.xy;

  // RGB 三通道分别用不同折射系数偏移（禁止合并为单值）
  // R 通道：uDispersionR（默认 0.075）
  float r = texture2D(uBackgroundTexture, vUv + baseOffset * uDispersionR).r;
  // G 通道：uDispersionG（默认 0.080）
  float g = texture2D(uBackgroundTexture, vUv + baseOffset * uDispersionG).g;
  // B 通道：uDispersionB（默认 0.085）
  float b = texture2D(uBackgroundTexture, vUv + baseOffset * uDispersionB).b;

  gl_FragColor = vec4(r, g, b, 1.0);
}
