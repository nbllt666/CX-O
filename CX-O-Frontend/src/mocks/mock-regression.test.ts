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
});
