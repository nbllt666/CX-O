import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest';
import { server } from './server';
import { VoiceActions, ChatActions, VoiceActionType } from '../constants/actions';

describe('Test3: Mock Regression - Phase 1 Governance', () => {
  beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
  afterEach(() => server.resetHandlers());
  afterAll(() => server.close());

  describe('Action Constants Module (H2)', () => {
    it('VoiceActions.DUAL_STREAM matches backend protocol string', () => {
      expect(VoiceActions.DUAL_STREAM).toBe('voice.dual_stream');
    });

    it('VoiceActions.PARTIAL matches backend protocol string', () => {
      expect(VoiceActions.PARTIAL).toBe('voice.partial');
    });

    it('VoiceActions.TTS_CHUNK matches backend protocol string', () => {
      expect(VoiceActions.TTS_CHUNK).toBe('voice.tts_chunk');
    });

    it('VoiceActions.PREFILL_STARTED matches backend protocol string', () => {
      expect(VoiceActions.PREFILL_STARTED).toBe('voice.prefill_started');
    });

    it('ChatActions.STREAM matches backend protocol string', () => {
      expect(ChatActions.STREAM).toBe('chat.stream');
    });

    it('VoiceActionType covers all voice message types', () => {
      const validTypes: VoiceActionType[] = [
        VoiceActions.PARTIAL,
        VoiceActions.TTS_CHUNK,
        VoiceActions.PREFILL_STARTED,
      ];
      expect(validTypes).toHaveLength(3);
      validTypes.forEach((t) => expect(t).toMatch(/^voice\./));
    });
  });

  describe('Mock API Contract - disconnectLiveClient (H1)', () => {
    it('mock server returns success for disconnect endpoint', async () => {
      const response = await fetch('http://localhost/api/live/client/test-001/disconnect', {
        method: 'POST',
      });
      const data = await response.json();
      expect(response.status).toBe(200);
      expect(data.status).toBe('success');
      expect(data.message).toContain('test-001');
    });

    it('mock server returns live client status', async () => {
      const response = await fetch('http://localhost/api/live/client/status');
      const data = await response.json();
      expect(response.status).toBe(200);
      expect(data.status).toBe('success');
    });
  });

  describe('Mock Handler Coverage', () => {
    it('health endpoint is mocked', async () => {
      const response = await fetch('http://localhost/api/health');
      expect(response.status).toBe(200);
    });

    it('agents endpoint is mocked', async () => {
      const response = await fetch('http://localhost/api/agents');
      expect(response.status).toBe(200);
    });

    it('chat history endpoint is mocked (H4 prep)', async () => {
      const response = await fetch('http://localhost/api/chat/history/agent-default');
      const data = await response.json();
      expect(response.status).toBe(200);
      expect(data.status).toBe('success');
      expect(Array.isArray(data.messages)).toBe(true);
    });

    it('chat stream endpoint returns SSE (H4 prep)', async () => {
      const response = await fetch('http://localhost/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'hello', agent_id: 'default' }),
      });
      expect(response.status).toBe(200);
      const text = await response.text();
      expect(text).toContain('data: ');
      expect(text).toContain('[DONE]');
      expect(text).toContain('mock-stream-1');
    });
  });

  describe('Mock API Contract - Tools & Memories (M19 prep)', () => {
    it('tools list endpoint returns tools map', async () => {
      const response = await fetch('http://localhost/api/tools');
      const data = await response.json();
      expect(response.status).toBe(200);
      expect(data.tools).toBeDefined();
      expect(typeof data.tools).toBe('object');
      expect(data.tools['tool-search']).toBeDefined();
      expect(data.tools['tool-search'].name).toBe('search_web');
    });

    it('tools stats endpoint returns statistics', async () => {
      const response = await fetch('http://localhost/api/tools/stats');
      const data = await response.json();
      expect(response.status).toBe(200);
      expect(data.status).toBe('success');
      expect(data.statistics.total_tools).toBe(2);
      expect(data.statistics.builtin_tools).toBe(2);
    });

    it('create tool endpoint returns new tool', async () => {
      const response = await fetch('http://localhost/api/tools', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'new_tool', description: 'test' }),
      });
      const data = await response.json();
      expect(response.status).toBe(200);
      expect(data.id).toBe('tool-new-mock');
      expect(data.type).toBe('custom');
    });

    it('delete tool endpoint returns 204', async () => {
      const response = await fetch('http://localhost/api/tools/tool-1', {
        method: 'DELETE',
      });
      expect(response.status).toBe(204);
    });

    it('memories list endpoint returns memories array', async () => {
      const response = await fetch('http://localhost/api/memories');
      const data = await response.json();
      expect(response.status).toBe(200);
      expect(Array.isArray(data.memories)).toBe(true);
      expect(data.memories.length).toBe(2);
      expect(data.memories[0].content).toContain('Mocked');
    });

    it('memories agents endpoint returns agent tables', async () => {
      const response = await fetch('http://localhost/api/memories/agents');
      const data = await response.json();
      expect(response.status).toBe(200);
      expect(data.agents).toBeDefined();
      expect(data.agents[0].agent_id).toBe('default');
    });

    it('create memory endpoint returns new memory', async () => {
      const response = await fetch('http://localhost/api/memories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: 'test memory', type: 'long_term' }),
      });
      const data = await response.json();
      expect(response.status).toBe(200);
      expect(data.id).toBe(999);
      expect(data.content).toBe('test memory');
    });

    it('archive memory endpoint returns 204', async () => {
      const response = await fetch('http://localhost/api/archive/memory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memory_id: 1, target_level: 1 }),
      });
      expect(response.status).toBe(204);
    });
  });
});
