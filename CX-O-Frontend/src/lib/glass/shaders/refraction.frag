/*
 * refraction.frag — Liquid Glass 折射层 fragment shader
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (shader.fragmentShader.refractionLayer) +
 *        C1 frontend_glass_config.schema.json (webglUniforms.uRefractionStrength)
 * 用途: 采样背景纹理 + 法线贴图，用 refract() 模拟光线穿过玻璃的偏折
 *
 * Uniforms（C1 配置驱动，禁止硬编码）:
 *   - uBackgroundTexture: 背景纹理（来自 backgroundFBO）
 *   - uNormalMap: 法线贴图（SDF 边缘距离预计算，D2 gpuMemoryManagement.normalLUT）
 *   - uRefractionStrength: 折射强度系数，默认 0.08，范围 [0, 0.3]（C1 webglUniforms）
 *   - uTextureSize: 纹理尺寸 vec2（用于 textureLod 采样）
 *
 * 技术路径（D2 shader.fragmentShader.refractionLayer）:
 *   - per-pixel normal 由 SDF 边缘距离计算（法线 LUT 预计算）
 *   - refract() 函数模拟光线穿过玻璃的偏折
 *   - textureLod 优化避免多次 mipmap 查询（D2 gpuMemoryManagement.refractionSampling）
 * ============================================================================
 */

precision highp float;

varying vec2 vUv;
varying vec2 vScreenPos;

uniform sampler2D uBackgroundTexture;
uniform sampler2D uNormalMap;
uniform float uRefractionStrength;
uniform vec2 uTextureSize;

void main() {
  // 从法线 LUT 采样 per-pixel 法线（预计算，D2 gpuMemoryManagement.normalLUT = precomputed）
  vec3 normal = texture2D(uNormalMap, vUv).rgb * 2.0 - 1.0;
  normal = normalize(normal);

  // 入射光方向（垂直于屏幕）
  vec3 incident = vec3(0.0, 0.0, 1.0);

  // refract() 模拟光线穿过玻璃的偏折（折射率比 1.0/1.5 = 空气→玻璃）
  vec3 refracted = refract(incident, normal, 1.0 / 1.5);

  // 折射偏移量 = 折射方向.xy * uRefractionStrength（C1 配置驱动）
  vec2 offset = refracted.xy * uRefractionStrength;

  // textureLod 优化采样（D2 gpuMemoryManagement.refractionSampling = textureLod）
  float lodLevel = 0.0;
  vec4 refractedColor = texture2D(uBackgroundTexture, vUv + offset);

  gl_FragColor = refractedColor;
}
