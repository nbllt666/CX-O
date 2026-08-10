import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import VectorDataPage from './VectorDataPage';
import i18n from '../../i18n';
import { vectorApi } from '@/api/clients/vector';
import type { VectorStats } from '@/api/clients/vector';
import type { VectorData } from '@/api/types';

/**
 * VectorDataPage 冒烟 + 关键交互测试（SubTask 7.3）：
 * vectorApi 整体打桩；覆盖统计渲染、未启用态、列表与分页参数、
 * 语义搜索弹窗、删除确认、同步操作、加载失败重试。
 */
vi.mock('@/api/clients/vector', () => ({
  vectorApi: {
    getVectorStats: vi.fn(),
    listVectors: vi.fn(),
    searchVectors: vi.fn(),
    getVector: vi.fn(),
    deleteVector: vi.fn(),
    syncVectors: vi.fn(),
    rebuildVectors: vi.fn(),
  },
}));

const mocked = vi.mocked(vectorApi);

const SAMPLE_STATS: VectorStats = {
  vector_enabled: true,
  total_vectors: 180,
  total_memories: 200,
  indexed_ratio: 0.9,
  backend: 'weaviate',
  collection_info: { name: 'memories', dim: 1024 },
};

const SAMPLE_VECTORS: VectorData[] = [
  {
    memory_id: 1,
    content: '用户喜欢二次元风格',
    memory_type: 'long_term',
    importance: 8,
    created_at: '2026-08-06 12:00:00',
    has_vector: true,
  },
  {
    memory_id: 2,
    content: '今天讨论了前端架构',
    memory_type: 'short_term',
    importance: 5,
    created_at: '2026-08-07 09:30:00',
    has_vector: true,
  },
];

describe('VectorDataPage 向量数据页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染统计行、向量列表与集合信息', async () => {
    mocked.getVectorStats.mockResolvedValue(SAMPLE_STATS);
    mocked.listVectors.mockResolvedValue({ vectors: SAMPLE_VECTORS, total: 2 });

    render(<VectorDataPage />);

    expect(await screen.findByText('用户喜欢二次元风格')).toBeInTheDocument();
    expect(screen.getByText('今天讨论了前端架构')).toBeInTheDocument();
    expect(screen.getByText('向量总数')).toBeInTheDocument();
    expect(screen.getByText('记忆总数')).toBeInTheDocument();
    expect(screen.getByText('索引率')).toBeInTheDocument();
    expect(screen.getByText('90.0%')).toBeInTheDocument();
    expect(screen.getByText('weaviate')).toBeInTheDocument();
    // 集合信息 JSON
    expect(screen.getByText('集合信息')).toBeInTheDocument();
    expect(screen.getByText(/"dim": 1024/)).toBeInTheDocument();
    // 分页信息
    expect(screen.getByText(/共 2 条/)).toBeInTheDocument();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
    // listVectors 默认分页参数
    expect(mocked.listVectors).toHaveBeenCalledWith(50, 0, undefined);
  });

  it('向量存储未启用时展示引导卡片', async () => {
    mocked.getVectorStats.mockResolvedValue({ ...SAMPLE_STATS, vector_enabled: false });

    render(<VectorDataPage />);

    expect(await screen.findByText('向量数据库未启用')).toBeInTheDocument();
    expect(mocked.listVectors).not.toHaveBeenCalled();
  });

  it('语义搜索打开结果弹窗（含相似度徽章）', async () => {
    mocked.getVectorStats.mockResolvedValue(SAMPLE_STATS);
    mocked.listVectors.mockResolvedValue({ vectors: SAMPLE_VECTORS, total: 2 });
    mocked.searchVectors.mockResolvedValue({
      results: [{ ...SAMPLE_VECTORS[0], score: 0.912 } as VectorData],
    });

    render(<VectorDataPage />);
    expect(await screen.findByText('用户喜欢二次元风格')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('语义搜索...'), { target: { value: '二次元' } });
    fireEvent.click(screen.getByRole('button', { name: '搜索' }));

    expect(await screen.findByText('语义搜索结果')).toBeInTheDocument();
    expect(screen.getByText('相似度：0.912')).toBeInTheDocument();
    expect(mocked.searchVectors).toHaveBeenCalledWith('二次元', 10);
  });

  it('删除向量需确认，确认后调用 deleteVector', async () => {
    mocked.getVectorStats.mockResolvedValue(SAMPLE_STATS);
    mocked.listVectors.mockResolvedValue({ vectors: SAMPLE_VECTORS, total: 2 });
    mocked.deleteVector.mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<VectorDataPage />);
    expect(await screen.findByText('用户喜欢二次元风格')).toBeInTheDocument();

    const deleteButtons = screen.getAllByRole('button', { name: '删除' });
    fireEvent.click(deleteButtons[0]);
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
      expect(mocked.deleteVector).toHaveBeenCalledWith(1);
    });
    confirmSpy.mockRestore();
  });

  it('同步向量成功后显示完成提示', async () => {
    mocked.getVectorStats.mockResolvedValue(SAMPLE_STATS);
    mocked.listVectors.mockResolvedValue({ vectors: SAMPLE_VECTORS, total: 2 });
    mocked.syncVectors.mockResolvedValue({ status: 'success' });

    render(<VectorDataPage />);
    expect(await screen.findByText('用户喜欢二次元风格')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '同步向量' }));
    expect(await screen.findByText('同步完成：success')).toBeInTheDocument();
  });

  it('记忆 ID 直达打开详情弹窗', async () => {
    mocked.getVectorStats.mockResolvedValue(SAMPLE_STATS);
    mocked.listVectors.mockResolvedValue({ vectors: SAMPLE_VECTORS, total: 2 });
    mocked.getVector.mockResolvedValue(SAMPLE_VECTORS[1]);

    render(<VectorDataPage />);
    expect(await screen.findByText('用户喜欢二次元风格')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('记忆 ID'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: '直达' }));

    expect(await screen.findByText('向量详情')).toBeInTheDocument();
    expect(mocked.getVector).toHaveBeenCalledWith(2);
  });

  it('加载失败显示错误态，点击重试重新拉取', async () => {
    mocked.getVectorStats.mockRejectedValueOnce(new Error('network down'));

    render(<VectorDataPage />);
    expect(
      await screen.findByText('加载失败，请检查后端连接后重试'),
    ).toBeInTheDocument();

    mocked.getVectorStats.mockResolvedValue(SAMPLE_STATS);
    mocked.listVectors.mockResolvedValue({ vectors: SAMPLE_VECTORS, total: 2 });
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('用户喜欢二次元风格')).toBeInTheDocument();
  });
});
