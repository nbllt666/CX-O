/**
 * cluster 域客户端：CX-A 哨兵集群（Sentinel Cluster）访问层。
 * 端点面对齐后端 server（挂载前缀 /api）：
 *   GET  /api/cluster/topology
 *   GET  /api/cluster/state
 *   GET  /api/cluster/sync
 *   POST /api/cluster/takeover
 *
 * 降级口径（对齐 admin.ts）：
 * - 查询类（fetchTopology/fetchSync）失败返回 null，供 UI 降级展示。
 * - fetchState 为「启用网关」：cluster 未启用（state 拉取 503/失败）或后端离线时
 *   同样抛归一化错误（normalizeError），由 UI 区分「离线全页错误态」与「未启用徽章」。
 * - 触发类（postTakeover）抛归一化错误（normalizeError），供 UI 捕获提示。
 */
import { request, normalizeError } from '../base';

/** 拓扑节点（GET /api/cluster/topology） */
export interface ClusterNodeInfo {
  node_id: string;
  endpoint: string;
  role: string;
  state: string;
  last_heartbeat?: string | null;
  [key: string]: unknown;
}

/** 拓扑响应：{"topology": [...]} */
export interface ClusterTopology {
  topology: ClusterNodeInfo[];
}

/** 集群状态（GET /api/cluster/state）：{"state": {...}} */
export interface ClusterState {
  state: {
    node_id: string;
    role: string;
    epoch: number;
    enabled: boolean;
    peers?: string[];
    [key: string]: unknown;
  };
}

/** 备份单元同步进度（GET /api/cluster/sync）：{"sync":{"units":[...]}} */
export interface ClusterSyncUnit {
  name?: string;
  status?: string;
  synced?: number;
  total?: number;
  progress?: number;
  [key: string]: unknown;
}

/** 同步响应：{"sync":{"units":[...]}} */
export interface ClusterSyncInfo {
  sync: {
    units: ClusterSyncUnit[];
    [key: string]: unknown;
  };
}

/** 故障转移/接管指令载荷（POST /api/cluster/takeover） */
export interface ClusterTakeoverPayload {
  from_node: string;
  to_node?: string;
  params?: Record<string, unknown>;
}

/** 接管响应 */
export interface ClusterTakeoverResult {
  status: string;
  [key: string]: unknown;
}

export const clusterApi = {
  /**
   * 集群整体状态。cluster 未启用（state 拉取 503/失败）或后端离线时抛出归一化错误，
   * 由 UI 按错误类型区分「后端离线全页错误态」与「未启用徽章」。
   */
  async fetchState(): Promise<ClusterState> {
    try {
      return await request<ClusterState>({ url: '/api/cluster/state' });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 集群拓扑表；后端离线返回 null */
  async fetchTopology(): Promise<ClusterTopology | null> {
    try {
      return await request<ClusterTopology>({ url: '/api/cluster/topology' });
    } catch {
      return null;
    }
  },

  /** 备份单元同步进度；后端离线返回 null */
  async fetchSync(): Promise<ClusterSyncInfo | null> {
    try {
      return await request<ClusterSyncInfo>({ url: '/api/cluster/sync' });
    } catch {
      return null;
    }
  },

  /** 触发故障转移/接管（from_node → to_node）；失败抛归一化错误 */
  async postTakeover(
    from_node: string,
    to_node?: string,
    params?: Record<string, unknown>,
  ): Promise<ClusterTakeoverResult> {
    try {
      return await request<ClusterTakeoverResult>({
        url: '/api/cluster/takeover',
        method: 'post',
        data: { from_node, to_node, params } as ClusterTakeoverPayload,
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },
};