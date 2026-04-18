import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { PageHeader } from '../components/layout';
import { Button, Card, CardBody, Modal, Badge, Input } from '../components/ui';
import { GraphVisualization } from '../components/GraphVisualization';
import { cn } from '../lib/utils';

type LibraryType = 'user' | 'thing' | 'concept' | 'event';

interface Entity {
  entity_id: string;
  name: string;
  entity_type: string;
  properties: Record<string, unknown>;
  memory_ids: string[];
  created_at: string;
  updated_at: string;
}

interface Relation {
  from_entity: string;
  to_entity: string;
  relation_type: string;
  strength: number;
  from_entity_name?: string;
  to_entity_name?: string;
  created_at: string;
}

const libraryLabels: Record<LibraryType, { name: string; description: string; color: string }> = {
  user: { name: '用户图库', description: '人物、用户、联系人', color: 'bg-blue-500' },
  thing: { name: '事物图库', description: '物品、产品、地点', color: 'bg-green-500' },
  concept: { name: '概念图库', description: '概念、想法、主题', color: 'bg-purple-500' },
  event: { name: '事件图库', description: '事件、活动、发生', color: 'bg-orange-500' },
};

export function GraphDataPage() {
  const queryClient = useQueryClient();
  const [activeLibrary, setActiveLibrary] = useState<LibraryType>('user');
  const [activeTab, setActiveTab] = useState<'entities' | 'relations' | 'graph'>('graph');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [showEntityModal, setShowEntityModal] = useState(false);
  const [showRelationModal, setShowRelationModal] = useState(false);
  const [showPathModal, setShowPathModal] = useState(false);

  const [newEntity, setNewEntity] = useState({
    entity_id: '',
    name: '',
    entity_type: '',
    properties: '{}',
  });

  const [newRelation, setNewRelation] = useState({
    from_entity: '',
    to_entity: '',
    relation_type: '',
    strength: 1.0,
  });

  const [pathQuery, setPathQuery] = useState({
    start_entity: '',
    end_entity: '',
    max_depth: 3,
  });

  const { data: graphStatus } = useQuery({
    queryKey: ['graphStatus'],
    queryFn: () => api.getGraphStatus(),
  });

  const { data: entityTypes } = useQuery({
    queryKey: ['entityTypes', activeLibrary],
    queryFn: () => api.getGraphEntityTypes(activeLibrary),
  });

  const { data: relationTypes } = useQuery({
    queryKey: ['relationTypes', activeLibrary],
    queryFn: () => api.getGraphRelationTypes(activeLibrary),
  });

  const { data: entities, isLoading: entitiesLoading } = useQuery({
    queryKey: ['graphEntities', activeLibrary, searchQuery],
    queryFn: () => api.listGraphEntities(activeLibrary, { search: searchQuery || undefined, limit: 100 }),
    enabled: graphStatus?.graph_status?.connected,
  });

  const { data: relations, isLoading: relationsLoading } = useQuery({
    queryKey: ['graphRelations', activeLibrary],
    queryFn: () => api.listGraphRelations(activeLibrary, { limit: 100 }),
    enabled: graphStatus?.graph_status?.connected,
  });

  const createEntityMutation = useMutation({
    mutationFn: (data: typeof newEntity) =>
      api.createGraphEntity(activeLibrary, {
        entity_id: data.entity_id,
        name: data.name,
        entity_type: data.entity_type,
        properties: JSON.parse(data.properties || '{}'),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['graphEntities', activeLibrary] });
      setShowEntityModal(false);
      setNewEntity({ entity_id: '', name: '', entity_type: '', properties: '{}' });
    },
  });

  const deleteEntityMutation = useMutation({
    mutationFn: (entityId: string) => api.deleteGraphEntity(activeLibrary, entityId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['graphEntities', activeLibrary] });
    },
  });

  const createRelationMutation = useMutation({
    mutationFn: (data: typeof newRelation) =>
      api.createGraphRelation(activeLibrary, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['graphRelations', activeLibrary] });
      setShowRelationModal(false);
      setNewRelation({ from_entity: '', to_entity: '', relation_type: '', strength: 1.0 });
    },
  });

  const deleteRelationMutation = useMutation({
    mutationFn: (params: { from_entity: string; to_entity: string; relation_type: string }) =>
      api.deleteGraphRelation(activeLibrary, params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['graphRelations', activeLibrary] });
    },
  });

  const connected = graphStatus?.graph_status?.connected;

  return (
    <div className="max-w-7xl mx-auto">
      <PageHeader
        title="图数据库管理"
        description="管理 Neo4j 图数据库中的实体和关系"
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

      <div className="flex gap-6">
        <div className="w-48 flex-shrink-0 space-y-2">
          {(Object.keys(libraryLabels) as LibraryType[]).map((lib) => (
            <button
              key={lib}
              onClick={() => setActiveLibrary(lib)}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-lg)] text-sm font-medium transition-colors text-left',
                activeLibrary === lib
                  ? 'bg-[var(--color-accent-light)] text-[var(--color-accent)]'
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]'
              )}
            >
              <span className={cn('w-2 h-2 rounded-full', libraryLabels[lib].color)} />
              <div>
                <div>{libraryLabels[lib].name}</div>
                <div className="text-xs text-[var(--color-text-tertiary)] font-normal">
                  {libraryLabels[lib].description}
                </div>
              </div>
            </button>
          ))}

          {graphStatus?.graph_status?.libraries && (
            <div className="mt-4 p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
              <div className="text-xs text-[var(--color-text-tertiary)] mb-2">统计信息</div>
              {Object.entries(graphStatus.graph_status.libraries).map(([name, stats]: [string, unknown]) => {
                const s = stats as { entity_count?: number; relation_count?: number };
                return (
                  <div key={name} className="flex justify-between text-xs mb-1">
                    <span className="capitalize">{name}</span>
                    <span>{s.entity_count || 0} 实体 / {s.relation_count || 0} 关系</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          {!connected ? (
            <Card>
              <CardBody>
                <div className="text-center py-12">
                  <div className="text-4xl mb-4">🔗</div>
                  <h3 className="text-lg font-semibold mb-2">图数据库未连接</h3>
                  <p className="text-[var(--color-text-secondary)]">
                    请先在设置中启用并配置 Neo4j 图数据库
                  </p>
                </div>
              </CardBody>
            </Card>
          ) : (
            <>
              {/* 统计概览卡片 */}
              <div className="grid grid-cols-4 gap-4 mb-6">
                {(Object.keys(libraryLabels) as LibraryType[]).map((lib) => {
                  const stats = graphStatus?.graph_status?.libraries?.[lib] as { entity_count?: number; relation_count?: number } | undefined;
                  return (
                    <Card key={lib}>
                      <CardBody>
                        <div className="flex items-center gap-2 mb-2">
                          <span className={cn('w-2 h-2 rounded-full', libraryLabels[lib].color)} />
                          <span className="text-sm font-medium">{libraryLabels[lib].name}</span>
                        </div>
                        <div className="flex items-end justify-between">
                          <div>
                            <div className="text-2xl font-bold">{stats?.entity_count || 0}</div>
                            <div className="text-xs text-[var(--color-text-tertiary)]">实体</div>
                          </div>
                          <div className="text-right">
                            <div className="text-lg font-semibold text-[var(--color-text-secondary)]">{stats?.relation_count || 0}</div>
                            <div className="text-xs text-[var(--color-text-tertiary)]">关系</div>
                          </div>
                        </div>
                      </CardBody>
                    </Card>
                  );
                })}
              </div>

              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-4">
                  <button
                    onClick={() => setActiveTab('graph')}
                    className={cn(
                      'px-4 py-2 rounded-[var(--radius-md)] text-sm font-medium transition-colors',
                      activeTab === 'graph'
                        ? 'bg-[var(--color-accent)] text-white'
                        : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
                    )}
                  >
                    图谱视图
                  </button>
                  <button
                    onClick={() => setActiveTab('entities')}
                    className={cn(
                      'px-4 py-2 rounded-[var(--radius-md)] text-sm font-medium transition-colors',
                      activeTab === 'entities'
                        ? 'bg-[var(--color-accent)] text-white'
                        : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
                    )}
                  >
                    实体列表
                  </button>
                  <button
                    onClick={() => setActiveTab('relations')}
                    className={cn(
                      'px-4 py-2 rounded-[var(--radius-md)] text-sm font-medium transition-colors',
                      activeTab === 'relations'
                        ? 'bg-[var(--color-accent)] text-white'
                        : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
                    )}
                  >
                    关系列表
                  </button>
                  <button
                    onClick={() => setShowPathModal(true)}
                    className="px-4 py-2 rounded-[var(--radius-md)] text-sm font-medium bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]"
                  >
                    路径查询
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <Input
                    placeholder="搜索实体..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-64"
                  />
                  {activeTab === 'entities' && (
                    <Button onClick={() => setShowEntityModal(true)}>添加实体</Button>
                  )}
                  {activeTab === 'relations' && (
                    <Button onClick={() => setShowRelationModal(true)}>添加关系</Button>
                  )}
                </div>
              </div>

              {activeTab === 'graph' && (
                <div className="mb-6">
                  <GraphVisualization
                    nodes={
                      entities?.entities?.map((e: Entity) => ({
                        id: e.entity_id,
                        name: e.name,
                        type: e.entity_type,
                        val: 5,
                        data: e,
                      })) || []
                    }
                    links={
                      relations?.relations?.map((r: Relation) => ({
                        source: r.from_entity,
                        target: r.to_entity,
                        type: r.relation_type,
                        strength: r.strength,
                        data: r,
                      })) || []
                    }
                    width={800}
                    height={600}
                    onNodeClick={(node) => {
                      const entityData = node.data as unknown as Entity;
                      if (entityData && entityData.entity_id) {
                        setSelectedEntity(entityData);
                        setShowEntityModal(true);
                      }
                    }}
                  />
                </div>
              )}

              {activeTab === 'entities' && (
                <Card>
                  <CardBody>
                    {entitiesLoading ? (
                      <div className="text-center py-8">加载中...</div>
                    ) : entities?.entities?.length === 0 ? (
                      <div className="text-center py-8 text-[var(--color-text-secondary)]">
                        暂无实体数据
                      </div>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead className="bg-[var(--color-bg-tertiary)]">
                            <tr>
                              <th className="px-4 py-3 text-left">ID</th>
                              <th className="px-4 py-3 text-left">名称</th>
                              <th className="px-4 py-3 text-left">类型</th>
                              <th className="px-4 py-3 text-left">属性</th>
                              <th className="px-4 py-3 text-left">创建时间</th>
                              <th className="px-4 py-3 text-right">操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {entities?.entities?.map((entity: Entity) => (
                              <tr key={entity.entity_id} className="border-t border-[var(--color-border)]">
                                <td className="px-4 py-3 font-mono text-xs">{entity.entity_id}</td>
                                <td className="px-4 py-3 font-medium">{entity.name}</td>
                                <td className="px-4 py-3">
                                  <Badge variant="secondary">{entity.entity_type}</Badge>
                                </td>
                                <td className="px-4 py-3">
                                  <span className="text-[var(--color-text-tertiary)]">
                                    {Object.keys(entity.properties || {}).length} 个属性
                                  </span>
                                </td>
                                <td className="px-4 py-3 text-[var(--color-text-secondary)]">
                                  {entity.created_at ? new Date(entity.created_at).toLocaleString() : '-'}
                                </td>
                                <td className="px-4 py-3 text-right">
                                  <button
                                    onClick={() => {
                                      setSelectedEntity(entity);
                                      setShowEntityModal(true);
                                    }}
                                    className="text-[var(--color-accent)] hover:underline mr-3"
                                  >
                                    查看
                                  </button>
                                  <button
                                    onClick={() => {
                                      if (confirm(`确定删除实体 "${entity.name}"?`)) {
                                        deleteEntityMutation.mutate(entity.entity_id);
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
                  </CardBody>
                </Card>
              )}

              {activeTab === 'relations' && (
                <Card>
                  <CardBody>
                    {relationsLoading ? (
                      <div className="text-center py-8">加载中...</div>
                    ) : relations?.relations?.length === 0 ? (
                      <div className="text-center py-8 text-[var(--color-text-secondary)]">
                        暂无关系数据
                      </div>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead className="bg-[var(--color-bg-tertiary)]">
                            <tr>
                              <th className="px-4 py-3 text-left">起始实体</th>
                              <th className="px-4 py-3 text-left">关系类型</th>
                              <th className="px-4 py-3 text-left">目标实体</th>
                              <th className="px-4 py-3 text-left">强度</th>
                              <th className="px-4 py-3 text-left">创建时间</th>
                              <th className="px-4 py-3 text-right">操作</th>
                            </tr>
                          </thead>
                          <tbody>
                            {relations?.relations?.map((rel: Relation, idx: number) => (
                              <tr key={idx} className="border-t border-[var(--color-border)]">
                                <td className="px-4 py-3">
                                  <div className="font-medium">{rel.from_entity_name || rel.from_entity}</div>
                                  <div className="text-xs text-[var(--color-text-tertiary)]">{rel.from_entity}</div>
                                </td>
                                <td className="px-4 py-3">
                                  <Badge>{rel.relation_type}</Badge>
                                </td>
                                <td className="px-4 py-3">
                                  <div className="font-medium">{rel.to_entity_name || rel.to_entity}</div>
                                  <div className="text-xs text-[var(--color-text-tertiary)]">{rel.to_entity}</div>
                                </td>
                                <td className="px-4 py-3">{rel.strength}</td>
                                <td className="px-4 py-3 text-[var(--color-text-secondary)]">
                                  {rel.created_at ? new Date(rel.created_at).toLocaleString() : '-'}
                                </td>
                                <td className="px-4 py-3 text-right">
                                  <button
                                    onClick={() => {
                                      if (confirm('确定删除此关系?')) {
                                        deleteRelationMutation.mutate({
                                          from_entity: rel.from_entity,
                                          to_entity: rel.to_entity,
                                          relation_type: rel.relation_type,
                                        });
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
                  </CardBody>
                </Card>
              )}
            </>
          )}
        </div>
      </div>

      <Modal
        isOpen={showEntityModal}
        onClose={() => {
          setShowEntityModal(false);
          setSelectedEntity(null);
        }}
        title={selectedEntity ? '实体详情' : '添加实体'}
      >
        {selectedEntity ? (
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium">实体 ID</label>
              <div className="font-mono text-sm bg-[var(--color-bg-tertiary)] p-2 rounded">
                {selectedEntity.entity_id}
              </div>
            </div>
            <div>
              <label className="text-sm font-medium">名称</label>
              <div className="text-sm">{selectedEntity.name}</div>
            </div>
            <div>
              <label className="text-sm font-medium">类型</label>
              <div className="text-sm">{selectedEntity.entity_type}</div>
            </div>
            <div>
              <label className="text-sm font-medium">属性</label>
              <pre className="text-xs bg-[var(--color-bg-tertiary)] p-2 rounded overflow-auto max-h-40">
                {JSON.stringify(selectedEntity.properties, null, 2)}
              </pre>
            </div>
            <div>
              <label className="text-sm font-medium">关联记忆</label>
              <div className="text-sm">{selectedEntity.memory_ids?.length || 0} 条记忆</div>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">实体 ID</label>
              <Input
                value={newEntity.entity_id}
                onChange={(e) => setNewEntity({ ...newEntity, entity_id: e.target.value })}
                placeholder="唯一标识符"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">名称</label>
              <Input
                value={newEntity.name}
                onChange={(e) => setNewEntity({ ...newEntity, name: e.target.value })}
                placeholder="实体名称"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">实体类型</label>
              <select
                value={newEntity.entity_type}
                onChange={(e) => setNewEntity({ ...newEntity, entity_type: e.target.value })}
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
              >
                <option value="">选择类型</option>
                {entityTypes?.entity_types?.map((t: { value: string; label: string }) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">属性 (JSON)</label>
              <textarea
                value={newEntity.properties}
                onChange={(e) => setNewEntity({ ...newEntity, properties: e.target.value })}
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)] font-mono text-sm"
                rows={4}
                placeholder='{"key": "value"}'
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setShowEntityModal(false)}>
                取消
              </Button>
              <Button
                onClick={() => createEntityMutation.mutate(newEntity)}
                loading={createEntityMutation.isPending}
              >
                创建
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        isOpen={showRelationModal}
        onClose={() => setShowRelationModal(false)}
        title="添加关系"
      >
        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">起始实体 ID</label>
            <Input
              value={newRelation.from_entity}
              onChange={(e) => setNewRelation({ ...newRelation, from_entity: e.target.value })}
              placeholder="起始实体"
            />
          </div>
          <div>
            <label className="text-sm font-medium mb-2 block">关系类型</label>
            <select
              value={newRelation.relation_type}
              onChange={(e) => setNewRelation({ ...newRelation, relation_type: e.target.value })}
              className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
            >
              <option value="">选择类型</option>
              {relationTypes?.relation_types?.map((t: { value: string; label: string }) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-sm font-medium mb-2 block">目标实体 ID</label>
            <Input
              value={newRelation.to_entity}
              onChange={(e) => setNewRelation({ ...newRelation, to_entity: e.target.value })}
              placeholder="目标实体"
            />
          </div>
          <div>
            <label className="text-sm font-medium mb-2 block">关系强度</label>
            <Input
              type="number"
              value={newRelation.strength}
              onChange={(e) => setNewRelation({ ...newRelation, strength: parseFloat(e.target.value) || 1 })}
              min={0}
              max={1}
              step={0.1}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setShowRelationModal(false)}>
              取消
            </Button>
            <Button
              onClick={() => createRelationMutation.mutate(newRelation)}
              loading={createRelationMutation.isPending}
            >
              创建
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={showPathModal}
        onClose={() => setShowPathModal(false)}
        title="路径查询"
      >
        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">起始实体 ID</label>
            <Input
              value={pathQuery.start_entity}
              onChange={(e) => setPathQuery({ ...pathQuery, start_entity: e.target.value })}
              placeholder="起始实体"
            />
          </div>
          <div>
            <label className="text-sm font-medium mb-2 block">目标实体 ID</label>
            <Input
              value={pathQuery.end_entity}
              onChange={(e) => setPathQuery({ ...pathQuery, end_entity: e.target.value })}
              placeholder="目标实体"
            />
          </div>
          <div>
            <label className="text-sm font-medium mb-2 block">最大搜索深度</label>
            <Input
              type="number"
              value={pathQuery.max_depth}
              onChange={(e) => setPathQuery({ ...pathQuery, max_depth: parseInt(e.target.value) || 3 })}
              min={1}
              max={6}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setShowPathModal(false)}>
              取消
            </Button>
            <Button
              onClick={async () => {
                try {
                  const result = await api.findGraphPath(activeLibrary, pathQuery);
                  alert(`找到 ${result.path_count} 条路径`);
                } catch {
                  alert('路径查询失败');
                }
              }}
            >
              查询
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
