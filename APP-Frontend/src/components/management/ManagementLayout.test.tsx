import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import ManagementLayout from './ManagementLayout';
import { useChatStore } from '@/store/chatStore';
import { agentsApi } from '@/api/clients/agents';
import i18n from '@/i18n';

/**
 * ManagementLayout 增强侧边栏测试：
 * - A. 小工具分组可折叠/展开 + 路由落在子项自动展开
 * - B. 侧边栏整体折叠后，小工具分组不占位、子项平铺为图标
 * - C. 对话 Agent 子菜单：展开显示列表、点击切换并跳转 /chat
 * - D. 粒子装饰层常驻（data-particle-field）
 */
vi.mock('@/api/clients/agents', () => ({
  agentsApi: {
    getAgents: vi.fn(),
  },
}));

const mockedAgents = vi.mocked(agentsApi);

const SAMPLE_AGENTS = [
  { id: 'a1', name: 'Agent One', is_default: true },
  { id: 'a2', name: 'Agent Two', is_default: false },
];

function renderLayout(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/" element={<ManagementLayout />}>
          <Route index element={<div>dashboard-content</div>} />
          <Route path="chat" element={<div>chat-content</div>} />
          <Route path="vector" element={<div>vector-content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('ManagementLayout 增强侧边栏', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
    // framer-motion 在 jsdom 测 keyframe 时会调用 scrollTo（未实现），打桩静默
    window.scrollTo = () => {};
  });

  beforeEach(() => {
    // 复位 chatStore，避免 persist 跨用例污染
    useChatStore.setState({ agents: [], currentAgentId: null, isChatExpanded: false });
    mockedAgents.getAgents.mockResolvedValue(SAMPLE_AGENTS as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('D. 粒子装饰层常驻（樱花花瓣 + 星形）且 pointer-events none', () => {
    renderLayout('/');
    const decor = screen.getByTestId('particle-decor');
    expect(decor).toBeInTheDocument();
    expect(decor.className).toContain('pointer-events-none');
    expect(decor.querySelector('[data-particle-field="petal"]')).toBeInTheDocument();
    expect(decor.querySelector('[data-particle-field="star"]')).toBeInTheDocument();
  });

  it('A. 小工具分组默认折叠，点击「小工具」展开 4 个子项', () => {
    renderLayout('/');
    // 默认折叠：子项文本不可见
    expect(screen.queryByText('向量数据')).not.toBeInTheDocument();
    expect(screen.queryByText('音频测试')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '小工具' }));

    expect(screen.getByText('向量数据')).toBeInTheDocument();
    expect(screen.getByText('归档')).toBeInTheDocument();
    expect(screen.getByText('音频工作站')).toBeInTheDocument();
    expect(screen.getByText('音频测试')).toBeInTheDocument();
  });

  it('A. 路由落在小工具子项时自动展开分组', () => {
    renderLayout('/vector');
    // 命中 /vector → 自动展开分组（nav 子项「向量数据」+ 顶栏标题各出现一次）
    expect(screen.getAllByText('向量数据').length).toBeGreaterThan(0);
    expect(screen.getByText('vector-content')).toBeInTheDocument();
  });

  it('B. 整体折叠后：小工具分组不占位、子项平铺为图标（title 作 tooltip）', () => {
    renderLayout('/');
    // 展开态：分组按钮显示「小工具」
    expect(screen.getByRole('button', { name: '小工具' })).toBeInTheDocument();

    // 折叠侧边栏
    fireEvent.click(screen.getByRole('button', { name: '收起侧边栏' }));

    // 分组按钮消失（折叠态不再渲染分组头），子项平铺为图标
    expect(screen.queryByRole('button', { name: '小工具' })).not.toBeInTheDocument();
    expect(screen.getByTitle('向量数据')).toBeInTheDocument();
    expect(screen.getByTitle('归档')).toBeInTheDocument();
    expect(screen.getByTitle('音频工作站')).toBeInTheDocument();
    expect(screen.getByTitle('音频测试')).toBeInTheDocument();
  });

  it('C. 对话 Agent 子菜单：展开显示列表，点击切换 Agent 并跳转 /chat', async () => {
    renderLayout('/');
    expect(screen.queryByText('Agent One')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '对话' }));

    // 异步加载 Agent 列表
    expect(await screen.findByText('Agent One')).toBeInTheDocument();
    expect(screen.getByText('Agent Two')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Agent Two' }));

    // 切换当前 Agent 并导航到 /chat
    expect(useChatStore.getState().currentAgentId).toBe('a2');
    expect(screen.getByText('chat-content')).toBeInTheDocument();
  });

  it('C. 路由落在 /chat 时自动展开对话子菜单', async () => {
    renderLayout('/chat');
    expect(await screen.findByText('Agent One')).toBeInTheDocument();
    expect(screen.getByText('chat-content')).toBeInTheDocument();
  });
});
