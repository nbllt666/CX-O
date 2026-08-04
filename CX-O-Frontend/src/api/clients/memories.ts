/**
 * ApiClient mixin: memories & archive
 * Extracted from client.ts as part of M16 split.
 */
import { _ApiClientBase } from './_common';
import type { Memory, ArchiveStats, DuplicateGroup, ArchiveResult } from './_types';

export class _MemoriesClientMixin extends _ApiClientBase {
  async getMemories(params?: {
    type?: string;
    memory_type?: string;
    limit?: number;
    offset?: number;
    agent_id?: string;
  }): Promise<{ memories: Memory[] }> {
    return this.request<{ memories: Memory[] }>({
      url: '/api/memories',
      method: 'get',
      params
    });
  }

  async getAgentMemoryTables(): Promise<{ agents: { agent_id: string; table_name: string; created_at: string }[] }> {
    return this.request<{ agents: { agent_id: string; table_name: string; created_at: string }[] }>({ url: '/api/memories/agents' });
  }

  async createMemory(data: {
    content: string;
    type?: string;
    importance?: number;
    tags?: string[];
    agent_id?: string;
  }): Promise<Memory> {
    return this.request<Memory>({ url: '/api/memories', method: 'post', data });
  }

  async updateMemory(memoryId: number, data: Partial<Memory>): Promise<Memory> {
    return this.request<Memory>({ url: `/api/memories/${memoryId}`, method: 'put', data });
  }

  async deleteMemory(memoryId: number, softDelete: boolean = true): Promise<void> {
    await this.request({ url: `/api/memories/${memoryId}`, method: 'delete', params: { soft: softDelete } });
  }

  async archiveMemory(memoryId: number, targetLevel: number = 1): Promise<void> {
    await this.request({ url: '/api/archive/memory', method: 'post', data: { memory_id: memoryId, target_level: targetLevel } });
  }

  async searchMemories(query: string): Promise<{ memories: Memory[] }> {
    return this.request<{ memories: Memory[] }>({ url: '/api/memories/search', method: 'post', data: { query } });
  }

  async semanticSearch(query: string, options?: { limit?: number; min_score?: number }): Promise<{ results: Memory[] }> {
    return this.request<{ results: Memory[] }>({ url: '/api/memories/semantic-search', method: 'post', data: { query, ...options } });
  }

  async getMemoriesByType(type: string, params?: { limit?: number }): Promise<{ memories: Memory[] }> {
    return this.request<{ memories: Memory[] }>({ url: `/api/memories/type/${type}`, params });
  }

  async searchByTag(tag: string, params?: { limit?: number }): Promise<{ memories: Memory[] }> {
    return this.request<{ memories: Memory[] }>({ url: '/api/memories/tag', method: 'post', data: { tag, ...params } });
  }

  async batchDeleteMemories(memoryIds: number[]): Promise<void> {
    await this.request({ url: '/api/memories/batch-delete', method: 'post', data: { ids: memoryIds } });
  }

  async batchUpdateTags(memoryIds: number[], tags: string[], operation: 'add' | 'remove' | 'set'): Promise<void> {
    await this.request({ url: '/api/memories/batch-update-tags', method: 'post', data: { ids: memoryIds, tags, operation } });
  }

  async batchArchiveMemories(memoryIds: number[]): Promise<void> {
    await this.request({ url: '/api/memories/batch-archive', method: 'post', data: { ids: memoryIds } });
  }

  async batchRestoreMemories(memoryIds: number[]): Promise<void> {
    await this.request({ url: '/api/memories/batch-restore', method: 'post', data: { ids: memoryIds } });
  }

  async batchUpdateMemories(memoryIds: number[], updates: Partial<Memory>): Promise<void> {
    await this.request({ url: '/api/memories/batch-update', method: 'post', data: { ids: memoryIds, updates } });
  }

  async batchTagByQuery(query: string, tags: string[], operation: 'add' | 'remove' | 'set'): Promise<{ updated: number }> {
    return this.request<{ updated: number }>({ url: '/api/memories/batch-tag-by-query', method: 'post', data: { query, tags, operation } });
  }

  async batchDeleteByQuery(query: string): Promise<{ deleted: number }> {
    return this.request<{ deleted: number }>({ url: '/api/memories/batch-delete-by-query', method: 'post', data: { query } });
  }

  async batchArchiveByQuery(query: string, targetLevel: number = 1): Promise<{ archived: number }> {
    return this.request<{ archived: number }>({ url: '/api/memories/batch-archive-by-query', method: 'post', data: { query, target_level: targetLevel } });
  }

  async memoryChat(message: string, sessionId: string): Promise<{ response: string }> {
    return this.request<{ response: string }>({ url: '/api/memory-chat', method: 'post', data: { message, session_id: sessionId } });
  }

  async getStats(): Promise<{
    total_memories: number;
    total_sessions: number;
    total_agents: number;
    archived_memories: number;
    total_messages: number;
  }> {
    const response = await this.request<{
      status?: string;
      data: {
        total_memories: number;
        total_sessions: number;
        total_agents: number;
        archived_memories: number;
        total_messages: number;
      };
    }>({ url: '/api/stats' });
    return response.data;
  }

  async getArchiveStats(): Promise<ArchiveStats> {
    const response = await this.request<{ status?: string; statistics: ArchiveStats }>({ url: '/api/archive/stats' });
    return response.statistics;
  }

  async mergeMemories(memoryIds: number[]): Promise<{ success: boolean; merged_memory_id?: number }> {
    return this.request<{ success: boolean; merged_memory_id?: number }>({ url: '/api/archive/merge', method: 'post', data: { memory_ids: memoryIds } });
  }

  async detectDuplicates(): Promise<{ duplicate_groups: DuplicateGroup[] }> {
    return this.request<{ duplicate_groups: DuplicateGroup[] }>({ url: '/api/archive/deduplicate', method: 'post', data: {} });
  }

  async autoArchiveProcess(): Promise<ArchiveResult> {
    return this.request<ArchiveResult>({ url: '/api/archive/auto-process', method: 'post' });
  }

  /**
   * 获取日记条目（按日期分组）
   * 迁移自 CXHMS: 用于 MemoriesPage 日记 Tab 视图
   */
  async getDiaryEntries(params?: {
    limit?: number;
    agent_id?: string;
    workspace_id?: string;
  }): Promise<{
    diary_groups: Array<{
      date: string;
      entries: Array<{
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
      }>;
    }>;
    count?: number;
  }> {
    return this.request<{
      diary_groups: Array<{
        date: string;
        entries: Array<{
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
        }>;
      }>;
      count?: number;
    }>({
      url: '/api/memories/diary',
      method: 'get',
      params: {
        limit: params?.limit ?? 100,
        agent_id: params?.agent_id ?? 'default',
        workspace_id: params?.workspace_id ?? 'default',
      },
    });
  }
}
