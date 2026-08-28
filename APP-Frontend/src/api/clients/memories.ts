/**
 * memories 域客户端：记忆 CRUD / 搜索 / 批量操作 / 归档 / 日记。
 * 端点面对齐 CX-O-Frontend clients/memories.ts。
 */
import { request } from '../base';
import type { ArchiveResult, ArchiveStats, DuplicateGroup, Memory } from '../types';

export interface MemoryQueryParams {
  type?: string;
  memory_type?: string;
  limit?: number;
  offset?: number;
  agent_id?: string;
}

export interface MemoryCreateInput {
  content: string;
  type?: string;
  importance?: number;
  tags?: string[];
  agent_id?: string;
}

export interface MemoryStats {
  total_memories: number;
  total_sessions: number;
  total_agents: number;
  archived_memories: number;
  total_messages: number;
}

export interface DiaryEntry {
  id: number;
  content: string;
  metadata?: {
    date?: string;
    title?: string;
    mood?: string;
    body?: string;
    summarized_message_range?: string;
    source?: string;
  };
  created_at: string;
}

export interface DiaryGroupsResponse {
  diary_groups: Array<{ date: string; entries: DiaryEntry[] }>;
  count?: number;
}

export const memoriesApi = {
  getMemories(params?: MemoryQueryParams): Promise<{ memories: Memory[] }> {
    return request<{ memories: Memory[] }>({ url: '/api/memories', method: 'get', params });
  },

  getAgentMemoryTables(): Promise<{
    agents: { agent_id: string; table_name: string; created_at: string }[];
  }> {
    return request<{ agents: { agent_id: string; table_name: string; created_at: string }[] }>({
      url: '/api/memories/agents',
    });
  },

  createMemory(data: MemoryCreateInput): Promise<Memory> {
    return request<Memory>({ url: '/api/memories', method: 'post', data });
  },

  updateMemory(memoryId: number, data: Partial<Memory>): Promise<Memory> {
    return request<Memory>({ url: `/api/memories/${memoryId}`, method: 'put', data });
  },

  async deleteMemory(memoryId: number, softDelete = true): Promise<void> {
    await request({
      url: `/api/memories/${memoryId}`,
      method: 'delete',
      params: { soft_delete: softDelete },
    });
  },

  async archiveMemory(memoryId: number, targetLevel = 1): Promise<void> {
    await request({
      url: '/api/archive/memory',
      method: 'post',
      data: { memory_id: memoryId, target_level: targetLevel },
    });
  },

  searchMemories(query: string): Promise<{ memories: Memory[] }> {
    return request<{ memories: Memory[] }>({
      url: '/api/memories/search',
      method: 'post',
      data: { query },
    });
  },

  semanticSearch(
    query: string,
    options?: { limit?: number; min_score?: number },
  ): Promise<{ results: Memory[] }> {
    return request<{ results: Memory[] }>({
      url: '/api/memories/semantic-search',
      method: 'post',
      data: { query, ...options },
    });
  },

  getMemoriesByType(type: string, params?: { limit?: number }): Promise<{ memories: Memory[] }> {
    return request<{ memories: Memory[] }>({ url: `/api/memories/type/${type}`, params });
  },

  searchByTag(tag: string, params?: { limit?: number }): Promise<{ memories: Memory[] }> {
    return request<{ memories: Memory[] }>({
      url: '/api/memories/search-by-tag',
      method: 'get',
      params: { tag, ...params },
    });
  },

  async batchDeleteMemories(memoryIds: number[]): Promise<void> {
    await request({ url: '/api/memories/batch/delete', method: 'post', data: { ids: memoryIds } });
  },

  async batchUpdateTags(
    memoryIds: number[],
    tags: string[],
    operation: 'add' | 'remove' | 'set',
  ): Promise<void> {
    await request({
      url: '/api/memories/batch/tags',
      method: 'post',
      data: { ids: memoryIds, tags, operation },
    });
  },

  async batchArchiveMemories(memoryIds: number[]): Promise<void> {
    await request({ url: '/api/memories/batch/archive', method: 'post', data: { ids: memoryIds } });
  },

  async batchRestoreMemories(memoryIds: number[]): Promise<void> {
    await request({ url: '/api/memories/batch/restore', method: 'post', data: { ids: memoryIds } });
  },

  async batchUpdateMemories(memoryIds: number[], updates: Partial<Memory>): Promise<void> {
    await request({
      url: '/api/memories/batch/update',
      method: 'post',
      data: { ids: memoryIds, data: updates },
    });
  },

  batchTagByQuery(
    query: string,
    tags: string[],
    operation: 'add' | 'remove' | 'set',
  ): Promise<{ updated: number }> {
    return request<{ updated: number }>({
      url: '/api/memories/batch/tag-by-query',
      method: 'post',
      data: { query, tags, operation },
    });
  },

  batchDeleteByQuery(query: string): Promise<{ deleted: number }> {
    return request<{ deleted: number }>({
      url: '/api/memories/batch/delete-by-query',
      method: 'post',
      data: { query },
    });
  },

  batchArchiveByQuery(query: string, targetLevel = 1): Promise<{ archived: number }> {
    return request<{ archived: number }>({
      url: '/api/memories/batch/archive-by-query',
      method: 'post',
      data: { query, target_level: targetLevel },
    });
  },

  /** 对齐后端 MemoryChatResponse：{ status, message, session_id, pending_command?, data? } */
  memoryChat(
    message: string,
    sessionId: string,
  ): Promise<{
    status: string;
    message: string;
    session_id: string;
    pending_command?: Record<string, unknown> | null;
    data?: Record<string, unknown> | null;
  }> {
    return request<{
      status: string;
      message: string;
      session_id: string;
      pending_command?: Record<string, unknown> | null;
      data?: Record<string, unknown> | null;
    }>({
      url: '/api/memory-chat',
      method: 'post',
      data: { message, session_id: sessionId },
    });
  },

  /** 全局统计（后端返回 { status, data }，解包后返回） */
  async getStats(): Promise<MemoryStats> {
    const response = await request<{ status?: string; data: MemoryStats }>({ url: '/api/stats' });
    return response.data;
  },

  async getArchiveStats(): Promise<ArchiveStats> {
    const response = await request<{ status?: string; statistics: ArchiveStats }>({
      url: '/api/archive/stats',
    });
    return response.statistics;
  },

  /** 后端返回 { status, result }，解包返回 result（合并结果对象） */
  async mergeMemories(
    memoryIds: number[],
  ): Promise<{ success: boolean; merged_memory_id?: number; [k: string]: unknown }> {
    const resp = await request<{
      status: string;
      result: { success: boolean; merged_memory_id?: number; [k: string]: unknown };
    }>({
      url: '/api/archive/merge',
      method: 'post',
      data: { memory_ids: memoryIds },
    });
    return resp.result;
  },

  detectDuplicates(): Promise<{ duplicate_groups: DuplicateGroup[] }> {
    return request<{ duplicate_groups: DuplicateGroup[] }>({
      url: '/api/archive/deduplicate',
      method: 'post',
      data: {},
    });
  },

  autoArchiveProcess(): Promise<ArchiveResult> {
    return request<ArchiveResult>({ url: '/api/archive/auto-process', method: 'post' });
  },

  /** 日记条目（按日期分组） */
  getDiaryEntries(params?: {
    limit?: number;
    agent_id?: string;
    workspace_id?: string;
  }): Promise<DiaryGroupsResponse> {
    return request<DiaryGroupsResponse>({
      url: '/api/memories/diary',
      method: 'get',
      params: {
        limit: params?.limit ?? 100,
        agent_id: params?.agent_id ?? 'default',
        workspace_id: params?.workspace_id ?? 'default',
      },
    });
  },
};
