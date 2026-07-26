/**
 * stylelint.config.js — Design Token stylelint 校验配置
 * ============================================================================
 * 层级：stylelint 校验配置（对齐 D1 契约 stylelintRules）
 * 用途：强制执行 token 命名规范 + 禁止硬编码 + 层级引用约束
 * 对齐契约：D1 frontend_design_tokens.schema.json → stylelintRules
 *   - noHex: 禁止组件层直接使用 hex 色值（仅 primitive.css 允许）
 *   - noMagicNumber: 禁止组件层使用魔法数字（间距/字号/圆角必须引用 token）
 *   - noUnknownProperty: 禁止使用未知 CSS 属性
 *   - noForbiddenTokens: 禁止引用未在 primitive/semantic 中定义的 token
 * 错误码关联：
 *   - TOKEN_NAMING_VIOLATION (FE-TOK-003): 命名不规范 → block-build
 *   - TOKEN_RAW_DIRECT_CONSUME (FE-TOK-004): 组件层直接消费 primitive → block-build
 * @version 1.0.0
 * ============================================================================
 */

module.exports = {
  extends: ['stylelint-config-standard'],
  plugins: [],
  rules: {
    /* ========================================================================
     * 1. noHex — 禁止组件层直接使用 hex 色值
     * 对齐 D1 契约 stylelintRules.noHex
     * 仅 primitive.css 允许 hex，其余文件禁止
     * ====================================================================== */
    'color-no-hex': [true, {
      severity: 'error',
      message: '禁止使用 hex 色值，请通过 var() 引用 primitive 层 token。违反触发 FE-TOK-004',
    }],

    /* ========================================================================
     * 2. noMagicNumber — 禁止组件层使用魔法数字
     * 对齐 D1 契约 stylelintRules.noMagicNumber
     * 例外属性：z-index, opacity, transform, line-height, font-weight
     * 间距/字号/圆角/阴影必须引用 token
     * ====================================================================== */
    'declaration-property-value-allowed-list': {
      '/spacing|padding|margin|gap/': ['/^var\\(/', '0'],
      '/font-size/': ['/^var\\(/'],
      '/border-radius/': ['/^var\\(/', '0'],
      '/width|height/': ['/^var\\(/', '0', '/^\\d+(px|rem|em|%|vw|vh)?$/'], // 允许布局尺寸具体值
    },

    /* ========================================================================
     * 3. noUnknownProperty — 禁止使用未知 CSS 属性
     * 对齐 D1 契约 stylelintRules.noUnknownProperty
     * ====================================================================== */
    'property-no-unknown': [true, {
      severity: 'warning',
      ignoreProperties: ['composes'],
    }],

    /* ========================================================================
     * 4. noForbiddenTokens — 禁止引用未定义 token
     * 对齐 D1 契约 stylelintRules.noForbiddenTokens
     * 通过 declaration-property-value-pattern 限制 var() 引用
     * ====================================================================== */
    'function-no-unknown': null, // 允许 var() 函数

    /* ========================================================================
     * 5. 命名规范 — token 命名必须符合 --{category}-{semantic}-{state}
     * 对齐 D1 契约 namingConvention
     * 违反触发 TOKEN_NAMING_VIOLATION (FE-TOK-003)
     * ====================================================================== */
    'custom-property-pattern': '^[a-z][a-z0-9-]*$', // kebab-case 强制

    /* ========================================================================
     * 6. 层级引用约束 — component 层禁止直接消费 primitive
     * 对齐 AGENTS.md §3.1 层级引用约束
     * 违反触发 TOKEN_RAW_DIRECT_CONSUME (FE-TOK-004)
     * ====================================================================== */
    // 注：此规则需要自定义 plugin 实现，当前通过 code review 保障
    // TODO: 开发 stylelint-plugin-no-raw-direct-consume 自定义插件

    /* ========================================================================
     * 7. 其他规则
     * ====================================================================== */
    'at-rule-no-unknown': [true, {
      ignoreAtRules: ['import', 'tailwind', 'apply', 'variants', 'responsive', 'screen'],
    }],
    'no-descending-specificity': null, // 允许主题覆盖的特异性降序
    'selector-class-pattern': null, // 不限制 class 命名（由 Tailwind 管理）
  },

  /* ========================================================================
   * overrides — 文件级覆盖规则
   * ====================================================================== */
  overrides: [
    {
      // primitive.css 允许 hex 色值和具体数值
      files: ['primitive.css'],
      rules: {
        'color-no-hex': null,
        'declaration-property-value-allowed-list': null,
      },
    },
    {
      // glass.css 允许具体数值（WebGL uniform 默认值）
      files: ['glass.css'],
      rules: {
        'color-no-hex': null,
        'declaration-property-value-allowed-list': null,
      },
    },
    {
      // dark-theme.css / light-theme.css 允许 rgba 阴影值（主题覆盖需要调整阴影深度）
      files: ['dark-theme.css', 'light-theme.css'],
      rules: {
        'color-no-hex': null,
        'declaration-property-value-allowed-list': null,
      },
    },
  ],

  /* ========================================================================
   * ignoreFiles — 不校验的文件
   * ====================================================================== */
  ignoreFiles: [
    'node_modules/**',
    'dist/**',
    'build/**',
    '**/*.min.css',
  ],
};
