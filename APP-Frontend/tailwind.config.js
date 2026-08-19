/** @type {import('tailwindcss').Config} */
export default {
  // 以 data-theme 属性驱动暗色主题（与 src/styles/tokens.css 的 [data-theme="dark"] 对应）
  darkMode: ['selector', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // 说明：var 色需以「通道值 + <alpha-value>」定义，透明度修饰（bg-primary/80 等）
        // 才能生效；全色值保留在 tokens.css 的 --color-* 供组件直接 var() 引用。
        background: 'rgb(var(--bg-primary-channel) / <alpha-value>)',
        foreground: 'var(--text-primary)',
        surface: 'var(--bg-secondary)',
        primary: {
          DEFAULT: 'rgb(var(--color-primary-channel) / <alpha-value>)',
          foreground: 'var(--color-primary-foreground)',
        },
        secondary: {
          DEFAULT: 'rgb(var(--color-secondary-channel) / <alpha-value>)',
          foreground: 'var(--color-secondary-foreground)',
        },
        accent: {
          DEFAULT: 'rgb(var(--color-accent-channel) / <alpha-value>)',
          foreground: 'var(--color-accent-foreground)',
        },
        muted: {
          DEFAULT: 'var(--bg-tertiary)',
          foreground: 'var(--text-secondary)',
        },
        border: 'var(--border-color)',
        glass: 'var(--glass-bg)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        DEFAULT: 'var(--radius-md)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
        '2xl': 'var(--radius-2xl)',
      },
      transitionDuration: {
        fast: 'var(--duration-fast)',
        normal: 'var(--duration-normal)',
        slow: 'var(--duration-slow)',
      },
      fontFamily: {
        sans: ['var(--font-sans)'],
      },
    },
  },
  plugins: [],
};
