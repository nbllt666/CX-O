import { beforeEach, describe, expect, it } from 'vitest';
import type { AxiosAdapter } from 'axios';
import { clearApiCache, getHttpClient } from '../base';
import { agentsApi } from './agents';

describe('Agent 克隆后的列表缓存', () => {
  beforeEach(() => clearApiCache());

  it('克隆后立即读取服务端新列表，随后的无变更读取仍命中缓存', async () => {
    const client = getHttpClient();
    const originalAdapter = client.defaults.adapter;
    const rows = [{ id: 'a1', name: '原代理' }];
    let reads = 0;
    const adapter: AxiosAdapter = async (config) => {
      let data;
      if (config.method === 'post') {
        const agent = { id: 'a2', name: '副本' };
        rows.push(agent);
        data = { agent };
      } else {
        reads += 1;
        data = { agents: rows.map((row) => ({ ...row })) };
      }
      return { config, data, status: 200, statusText: 'OK', headers: {} };
    };
    client.defaults.adapter = adapter;
    try {
      expect(await agentsApi.getAgents()).toHaveLength(1);
      expect(await agentsApi.getAgents()).toHaveLength(1);
      expect(reads).toBe(1);
      await agentsApi.cloneAgent('a1');
      expect((await agentsApi.getAgents()).map((agent) => agent.id)).toEqual(['a1', 'a2']);
      expect(reads).toBe(2);
      expect(await agentsApi.getAgents()).toHaveLength(2);
      expect(reads).toBe(2);
    } finally {
      client.defaults.adapter = originalAdapter;
    }
  });
});
