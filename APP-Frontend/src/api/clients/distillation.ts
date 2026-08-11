/**
 * distillation 域客户端：蒸馏会话 CRUD / 推进 / 终结 / 批量切分 / 角色卡导入。
 * 端点对齐 server/core/distillation/api（/api/v1/distillation/*）。
 */
import { request } from '../base';

// ── 类型（对齐后端 distillation_service.py 请求/响应模型） ──

export type DistillationSourceType =
  | 'text'
  | 'character_card'
  | 'image'
  | 'video'
  | 'audio'
  | 'conversation_log';

export interface StartDistillationInput {
  source_type: DistillationSourceType;
  source_ref?: string;
  template_id: string;
  max_turns?: number;
  ask_user_on_ambiguity?: boolean;
}

export interface StartDistillationResult {
  session_id: string;
  initial_state: string;
  preread_summary?: string | null;
}

export interface AdvanceDistillationResult {
  session_id: string;
  current_state: string;
  agent_action: string;
  next_needed: boolean;
}

export interface FinalizeDistillationResult {
  stored: boolean;
  location: string;
  memory_id?: number | null;
  metadata: Record<string, unknown>;
  reason: string;
}

export interface DistillationTurn {
  [key: string]: unknown;
}

export interface DistillationSession {
  session_id: string;
  source_type: string;
  state: string;
  template_id: string;
  max_turns: number;
  ask_user_on_ambiguity: boolean;
  turns: DistillationTurn[];
  preread_summary?: string | null;
  ambiguity_questions: string[];
  extracted_content?: string | null;
  quality_score?: number | null;
  created_at: string;
  updated_at?: string | null;
  finalized_at?: string | null;
  is_finalized?: boolean;
  error_message?: string | null;
}

export interface BatchStartInput {
  source_type: DistillationSourceType;
  source_ref: string;
  template_id: string;
  max_turns?: number;
  ask_user_on_ambiguity?: boolean;
  chunk_size?: number;
  distillation_goal?: 'memory' | 'agent' | 'memory_and_agent';
  target_agent_id?: string | null;
}

export interface BatchStartResult {
  session_group_id: string;
  sessions: Array<{ session_id: string; chunk_index: number }>;
  total_chunks: number;
}

export interface BatchGroupStatus {
  session_group_id: string;
  sessions: Array<Record<string, unknown>>;
  completed_count: number;
  total_count: number;
}

export interface CharacterCardData {
  name: string;
  description?: string;
  personality?: string;
  scenario?: string;
  first_mes?: string;
  mes_example?: string;
  [key: string]: unknown;
}

export interface ParseCharacterCardResult {
  status: string;
  character_card_data: CharacterCardData;
  source_ref: string;
  source_ref_length: number;
}

export interface StartFromCharacterCardInput {
  character_card_data: CharacterCardData;
  template_id?: string;
  max_turns?: number;
  ask_user_on_ambiguity?: boolean;
  chunk_size?: number;
  distillation_goal?: 'memory' | 'agent' | 'memory_and_agent';
}

export interface StartFromCharacterCardResult {
  status: string;
  character_card_data: CharacterCardData;
  distillation: BatchStartResult;
}

export const distillationApi = {
  /** 启动单次蒸馏会话 */
  start(input: StartDistillationInput): Promise<StartDistillationResult> {
    return request<StartDistillationResult>({
      url: '/api/v1/distillation/start',
      method: 'post',
      data: input,
    });
  },

  /** 推进蒸馏状态机（支持回环与主动追问响应） */
  advance(sessionId: string, userResponse?: string): Promise<AdvanceDistillationResult> {
    return request<AdvanceDistillationResult>({
      url: `/api/v1/distillation/${sessionId}/advance`,
      method: 'post',
      data: { user_response: userResponse },
    });
  },

  /** 终结蒸馏会话 */
  finalize(sessionId: string, overrideDecision?: string): Promise<FinalizeDistillationResult> {
    return request<FinalizeDistillationResult>({
      url: `/api/v1/distillation/${sessionId}/finalize`,
      method: 'post',
      data: { override_decision: overrideDecision },
    });
  },

  /** 终结蒸馏并创建角色卡 Agent */
  finalizeAgent(sessionId: string, overrideDecision?: string): Promise<FinalizeDistillationResult> {
    return request<FinalizeDistillationResult>({
      url: `/api/v1/distillation/${sessionId}/finalize-agent`,
      method: 'post',
      data: { override_decision: overrideDecision },
    });
  },

  /** 查询蒸馏会话状态 */
  getSession(sessionId: string): Promise<DistillationSession> {
    return request<DistillationSession>({
      url: `/api/v1/distillation/${sessionId}`,
      method: 'get',
    });
  },

  /** 批量切分启动蒸馏 */
  startBatch(input: BatchStartInput): Promise<BatchStartResult> {
    return request<BatchStartResult>({
      url: '/api/v1/distillation/start-batch',
      method: 'post',
      data: input,
    });
  },

  /** 查询批量切分组状态 */
  getGroupStatus(groupId: string): Promise<BatchGroupStatus> {
    return request<BatchGroupStatus>({
      url: `/api/v1/distillation/group/${groupId}`,
      method: 'get',
    });
  },

  /** 解析 PNG / JSON 角色卡（multipart 文件上传） */
  async parseCharacterCard(file: File): Promise<ParseCharacterCardResult> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return request<ParseCharacterCardResult>({
      url: '/api/v1/distillation/parse-character-card',
      method: 'post',
      data: formData,
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  /** 从角色卡解析结果启动蒸馏 */
  startFromCharacterCard(input: StartFromCharacterCardInput): Promise<StartFromCharacterCardResult> {
    return request<StartFromCharacterCardResult>({
      url: '/api/v1/distillation/start-from-character-card',
      method: 'post',
      data: input,
    });
  },
};