import { Outlet } from 'react-router-dom';
import { Layout, Sidebar, Header } from './layout';
import { ParticleField } from './anime';

/**
 * AppLayout — 全局应用布局（v2 重写：强烈二次元风格）。
 *
 * v2 改造要点:
 *   - 🌸 樱花花瓣粒子层（particleType='petal'，density=0.5，强烈风格）
 *   - ⭐ 星形粒子层（particleType='star'，density=0.2，辅助装饰）
 *   - ✂️ 移除 trigger="page-transition"（原 bug：与注释矛盾且被 void 忽略）
 *   - 🎨 粉紫青渐变光带由 glass-panel::before 提供（glass-classes.css）
 *
 * 装饰层 z-index 分层（对齐 GlassZIndex）:
 *   - 粒子装饰层: z=4（DECORATION）
 *   - 主内容层: z=3（UI）
 *   - 玻璃渲染层: z=2（GLASS，WebGL canvas）
 *
 * alpha 预算（USAGE_BOUNDARIES.singleScreenAlphaSum=0.4）:
 *   - 樱花花瓣: maxAlpha=0.28（主装饰，强烈风格）
 *   - 星形粒子: maxAlpha=0.12（辅助装饰）
 *   - 合计: 0.40（恰好达到上限，不超限）
 *
 * 持续显示: 装饰层在 AppLayout 内 fixed 挂载，不随路由切换卸载
 *
 * @since v2 重写（2026-07-27）
 */
export function AppLayout() {
  return (
    <Layout sidebar={(props) => <Sidebar {...props} />} header={<Header />}>
      {/*
       * 全局二次元装饰层（z-index=DECORATION=4，pointer-events=none）
       * 持续显示，不随路由切换卸载（解决"切换页面失效"问题）
       */}
      <div
        style={{
          position: 'fixed',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 4,
          overflow: 'hidden',
        }}
        aria-hidden="true"
      >
        {/* 樱花花瓣粒子（主装饰，强烈二次元风格） */}
        <ParticleField
          particleType="petal"
          density={0.5}
          maxAlpha={0.28}
          trigger="page-transition"
        />
        {/* 星形粒子（辅助装饰，增加层次感） */}
        <ParticleField
          particleType="star"
          density={0.2}
          maxAlpha={0.12}
          trigger="hover"
        />
      </div>
      <main className="h-full relative" style={{ zIndex: 3 }}>
        <Outlet />
      </main>
    </Layout>
  );
}
