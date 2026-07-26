/**
 * @file app-layout.tsx — AppLayout 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组布局类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\app-layout.tsx
 * 原组件: src/components/AppLayout.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（Outlet 路由出口 / Layout / Sidebar / Header 组合不变）
 *   - 注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出（glass 基础设施）
 *   - 仅 import 本模块内部实现（./layout）
 *   - 仅 import 第三方库 react-router-dom / framer-motion
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import { Outlet } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Layout, Sidebar, Header } from './layout';
import { buildGlassDataAttributes } from '@/components/ui-v2';

export function AppLayout() {
  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <Layout sidebar={(props) => <Sidebar {...props} />} header={<Header />}>
      <motion.main className="h-full" {...glassAttributes}>
        <Outlet />
      </motion.main>
    </Layout>
  );
}
