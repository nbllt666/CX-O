import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { PageHeader } from '@/components/business/layout';
import { Button, Card, CardBody, Badge, Input } from '@/components/ui-v2';
import { Modal } from '@/components/business/ui';
import { TimeAxis, TimeAxisDataPoint } from '@/components/business/time-axis';

interface Vector {
  memory_id: number;
  content: string;
  memory_type: string;
  importance: number;
  created_at: string;
  has_vector: boolean;
}

interface VectorStats {
  vector_enabled: boolean;
  total_vectors: number;
  total_memories: number;
  indexed_ratio: number;
  backend: string;
  collection_info: Record<string, unknown>;
}

export function VectorDataPage() {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');
  const [memoryTypeFilter, setMemoryTypeFilter] = useState<string>('');
  const [showSearchModal, setShowSearchModal] = useState(false);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [selectedVector, setSelectedVector] = useState<Vector | null>(null);
  const [searchResults, setSearchResults] = useState<unknown[]>([]);
  const [timeRange, setTimeRange] = useState<{ start: Date; end: Date } | null>(null);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [idLookup, setIdLookup] = useState('');

  const { data: vectorStatus, isLoading: statusLoading } = useQuery({
    queryKey: ['vectorStatus'],
    queryFn: () => api.getVectorStatus(),
  });

  const { data: vectorStats } = useQuery({
    queryKey: ['vectorStats'],
    queryFn: () => api.getVectorStats(),
  });

  const { data: vectors, isLoading: vectorsLoading } = useQuery({
    queryKey: ['vectors', memoryTypeFilter, page, pageSize],
    queryFn: () => api.listVectors(pageSize, page * pageSize, memoryTypeFilter || undefined),
    enabled: Boolean(vectorStatus?.connected),
    select: (data) => {
      if (!timeRange || !data.vectors) return data;
      return {
        ...data,
        vectors: (data.vectors as Vector[]).filter((v: Vector) => {
          const vectorDate = new Date(v.created_at);
          return vectorDate >= timeRange.start && vectorDate <= timeRange.end;
        }),
      };
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => api.syncVectors(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['vectors'] });
      queryClient.invalidateQueries({ queryKey: ['vectorStats'] });
      alert(`同步完成: ${data.status}`);
    },
  });

  const rebuildMutation = useMutation({
    mutationFn: () => api.rebuildVectors(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['vectors'] });
      queryClient.invalidateQueries({ queryKey: ['vectorStats'] });
      alert(`重建完成: ${data.status}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (memoryId: number) => api.deleteVector(memoryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vectors'] });
      queryClient.invalidateQueries({ queryKey: ['vectorStats'] });
    },
  });

  const connected = vectorStatus?.connected;
  const stats = vectorStats as VectorStats | undefined;
  const totalVectors = vectors?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalVectors / pageSize));

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    try {
      const result = await api.searchVectors(searchQuery, 10);
      setSearchResults(result.results || []);
      setShowSearchModal(true);
    } catch {
      alert('搜索失败');
    }
  };

  /** 打开详情弹窗：行内详情传入当前行数据，ID 直达仅传 memoryId（字段从接口兜底） */
  const openDetail = async (memoryId: number, baseRow?: Vector) => {
    try {
      const detail = (await api.getVector(memoryId)) as { vector?: Record<string, unknown> };
      const extra = (detail.vector ?? {}) as Record<string, unknown>;
      const mem = (extra.memory ?? {}) as Record<string, unknown>;
      const fallback: Vector = baseRow ?? {
        memory_id: memoryId,
        content: String(mem.content || ''),
        memory_type: String(mem.type || '-'),
        importance: Number(mem.importance ?? 0),
        created_at: String(mem.created_at || ''),
        has_vector: true,
      };
      setSelectedVector({ ...fallback, ...extra });
      setShowDetailModal(true);
    } catch {
      alert('获取详情失败或向量不存在');
    }
  };

  const handleIdLookup = () => {
    const id = parseInt(idLookup, 10);
    if (!Number.isFinite(id) || id <= 0) {
      alert('请输入有效的记忆 ID');
      return;
    }
    openDetail(id);
  };

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['vectors'] });
    queryClient.invalidateQueries({ queryKey: ['vectorStats'] });
    queryClient.invalidateQueries({ queryKey: ['vectorStatus'] });
  };

  return (
    <div className="max-w-7xl mx-auto px-6 h-full overflow-y-auto pb-6">
      <PageHeader
        title="向量数据库管理"
        description="管理向量数据库中的嵌入向量"
        actions={
          <div className="flex items-center gap-2">
            <span
              className={`w-3 h-3 rounded-full ${
                connected ? 'bg-green-500' : 'bg-red-500'
              }`}
            />
            <span className="text-sm text-[var(--color-text-secondary)]">
              {connected ? '已连接' : '未连接'}
            </span>
          </div>
        }
      />

      {statusLoading ? (
        <Card>
          <CardBody>
            <div className="text-center py-8">加载中...</div>
          </CardBody>
        </Card>
      ) : !connected ? (
        <Card>
          <CardBody>
            <div className="text-center py-12">
              <div className="text-4xl mb-4">📊</div>
              <h3 className="text-lg font-semibold mb-2">向量数据库未连接</h3>
              <p className="text-[var(--color-text-secondary)]">
                请先在设置中启用并配置向量数据库
              </p>
            </div>
          </CardBody>
        </Card>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-4 gap-4">
            <Card>
              <CardBody>
                <div className="text-sm text-[var(--color-text-tertiary)]">向量总数</div>
                <div className="text-2xl font-bold">{stats?.total_vectors || 0}</div>
              </CardBody>
            </Card>
            <Card>
              <CardBody>
                <div className="text-sm text-[var(--color-text-tertiary)]">记忆总数</div>
                <div className="text-2xl font-bold">{stats?.total_memories || 0}</div>
              </CardBody>
            </Card>
            <Card>
              <CardBody>
                <div className="text-sm text-[var(--color-text-tertiary)]">索引率</div>
                <div className="text-2xl font-bold">
                  {((stats?.indexed_ratio || 0) * 100).toFixed(1)}%
                </div>
              </CardBody>
            </Card>
            <Card>
              <CardBody>
                <div className="text-sm text-[var(--color-text-tertiary)]">后端</div>
                <div className="text-2xl font-bold">{stats?.backend || 'unknown'}</div>
              </CardBody>
            </Card>
          </div>

          {/* 时间轴组件 */}
          {vectors?.vectors && vectors.vectors.length > 0 && (
            <TimeAxis
              data={
                (vectors.vectors as Vector[]).reduce((acc: TimeAxisDataPoint[], vec: Vector) => {
                  const date = new Date(vec.created_at);
                  const dateStr = date.toISOString();
                  const existing = acc.find((a: TimeAxisDataPoint) => a.timestamp === dateStr);
                  if (existing) {
                    existing.count += 1;
                  } else {
                    acc.push({ timestamp: dateStr, count: 1 });
                  }
                  return acc;
                }, [] as TimeAxisDataPoint[])
                .sort((a: TimeAxisDataPoint, b: TimeAxisDataPoint) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
              }
              width={800}
              height={120}
              onTimeRangeChange={(start, end) => {
                console.log('时间范围变化:', start, end);
              }}
              onTimeRangeSelected={(start, end) => {
                setTimeRange({ start, end });
              }}
            />
          )}

          <Card>
            <CardBody>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">向量操作</h3>
              </div>
              <div className="flex items-center gap-4 flex-wrap">
                <div className="flex-1 flex items-center gap-2 min-w-[240px]">
                  <Input
                    placeholder="语义搜索..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                    className="flex-1"
                  />
                  <Button onClick={handleSearch}>搜索</Button>
                </div>
                <div className="flex items-center gap-2">
                  <Input
                    placeholder="记忆 ID"
                    value={idLookup}
                    onChange={(e) => setIdLookup(e.target.value.replace(/\D/g, ''))}
                    onKeyDown={(e) => e.key === 'Enter' && handleIdLookup()}
                    className="w-28"
                  />
                  <Button variant="secondary" onClick={handleIdLookup}>
                    直达
                  </Button>
                </div>
                <Button variant="secondary" onClick={handleRefresh}>
                  刷新
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => syncMutation.mutate()}
                  loading={syncMutation.isPending}
                >
                  同步向量
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => {
                    if (confirm('确定要重建所有向量吗？这将清空现有向量并重新生成。')) {
                      rebuildMutation.mutate();
                    }
                  }}
                  loading={rebuildMutation.isPending}
                >
                  重建向量
                </Button>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardBody>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">向量列表</h3>
                <select
                  value={memoryTypeFilter}
                  onChange={(e) => {
                    setMemoryTypeFilter(e.target.value);
                    setPage(0);
                  }}
                  className="px-3 py-2 bg-[var(--glass-surface)] border border-[var(--glass-border)] rounded-[var(--radius-md)] text-[var(--color-text-[var(--color-accent)])]"
                >
                  <option value="">全部类型</option>
                  <option value="short_term">短期记忆</option>
                  <option value="long_term">长期记忆</option>
                  <option value="working">工作记忆</option>
                  <option value="episodic">情景记忆</option>
                </select>
              </div>

              {vectorsLoading ? (
                <div className="text-center py-8">加载中...</div>
              ) : vectors?.vectors?.length === 0 ? (
                <div className="text-center py-8 text-[var(--color-text-secondary)]">
                  暂无向量数据
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-[var(--color-bg-tertiary)]">
                      <tr>
                        <th className="px-4 py-3 text-left">记忆 ID</th>
                        <th className="px-4 py-3 text-left">内容预览</th>
                        <th className="px-4 py-3 text-left">类型</th>
                        <th className="px-4 py-3 text-left">重要性</th>
                        <th className="px-4 py-3 text-left">创建时间</th>
                        <th className="px-4 py-3 text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(vectors?.vectors as Vector[] | undefined)?.map((vec: Vector) => (
                        <tr key={vec.memory_id} className="border-t border-[var(--color-border)]">
                          <td className="px-4 py-3 font-mono">{vec.memory_id}</td>
                          <td className="px-4 py-3 max-w-xs truncate">{vec.content}</td>
                          <td className="px-4 py-3">
                            <Badge variant="secondary">{vec.memory_type}</Badge>
                          </td>
                          <td className="px-4 py-3">{vec.importance}</td>
                          <td className="px-4 py-3 text-[var(--color-text-secondary)]">
                            {vec.created_at ? new Date(vec.created_at).toLocaleString() : '-'}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button
                              onClick={() => openDetail(vec.memory_id, vec)}
                              className="text-[var(--color-accent)] hover:underline mr-3"
                            >
                              详情
                            </button>
                            <button
                              onClick={() => {
                                if (confirm('确定删除此向量?')) {
                                  deleteMutation.mutate(vec.memory_id);
                                }
                              }}
                              className="text-red-500 hover:underline"
                            >
                              删除
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* 分页栏 */}
              <div className="flex items-center justify-between mt-4 text-sm text-[var(--color-text-secondary)]">
                <span>
                  共 {totalVectors} 条 · 第 {page + 1} / {totalPages} 页
                </span>
                <div className="flex items-center gap-2">
                  <select
                    value={pageSize}
                    onChange={(e) => {
                      setPageSize(Number(e.target.value));
                      setPage(0);
                    }}
                    className="px-2 py-1.5 bg-[var(--glass-surface)] border border-[var(--glass-border)] rounded-[var(--radius-md)]"
                  >
                    <option value={20}>20 条/页</option>
                    <option value={50}>50 条/页</option>
                    <option value={100}>100 条/页</option>
                  </select>
                  <Button
                    variant="secondary"
                    disabled={page === 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                  >
                    上一页
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={page + 1 >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  >
                    下一页
                  </Button>
                </div>
              </div>
            </CardBody>
          </Card>

          {stats?.collection_info && Object.keys(stats.collection_info).length > 0 && (
            <Card>
              <CardBody>
                <h3 className="text-lg font-semibold mb-4">集合信息</h3>
                <pre className="text-xs bg-[var(--color-bg-tertiary)] p-4 rounded overflow-auto max-h-60">
                  {JSON.stringify(stats.collection_info, null, 2)}
                </pre>
              </CardBody>
            </Card>
          )}
        </div>
      )}

      <Modal
        isOpen={showSearchModal}
        onClose={() => setShowSearchModal(false)}
        title="语义搜索结果"
      >
        <div className="space-y-4 max-h-96 overflow-auto">
          {searchResults.length === 0 ? (
            <div className="text-center py-4 text-[var(--color-text-secondary)]">
              未找到相关结果
            </div>
          ) : (
            searchResults.map((result: unknown, idx: number) => {
              const r = result as Record<string, unknown>;
              const memory = r.memory as Record<string, unknown> | undefined;
              const content = String(memory?.content || r.content || '无内容');
              const id = String(r.memory_id || r.id || '');
              return (
                <div key={idx} className="p-3 bg-[var(--color-bg-tertiary)] rounded">
                  <div className="flex items-center justify-between mb-2">
                    <Badge>相似度: {((r.score as number) || 0).toFixed(3)}</Badge>
                    <span className="text-xs text-[var(--color-text-tertiary)]">
                      ID: {id}
                    </span>
                  </div>
                  <div className="text-sm">
                    {content}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </Modal>

      <Modal
        isOpen={showDetailModal}
        onClose={() => {
          setShowDetailModal(false);
          setSelectedVector(null);
        }}
        title="向量详情"
      >
        {selectedVector && (
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium">记忆 ID</label>
              <div className="font-mono">{selectedVector.memory_id}</div>
            </div>
            <div>
              <label className="text-sm font-medium">向量维度</label>
              <div>{String((selectedVector as unknown as Record<string, unknown>).vector_size || 'N/A')}</div>
            </div>
            <div>
              <label className="text-sm font-medium">记忆类型</label>
              <div>{selectedVector.memory_type}</div>
            </div>
            <div>
              <label className="text-sm font-medium">内容</label>
              <pre className="text-xs bg-[var(--color-bg-tertiary)] p-2 rounded overflow-auto max-h-40">
                {String(((selectedVector as unknown as Record<string, unknown>).memory as Record<string, unknown>)?.content || selectedVector.content || '')}
              </pre>
            </div>
            <div>
              <label className="text-sm font-medium">元数据</label>
              <pre className="text-xs bg-[var(--color-bg-tertiary)] p-2 rounded overflow-auto max-h-40">
                {JSON.stringify((selectedVector as unknown as Record<string, unknown>).metadata || {}, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
