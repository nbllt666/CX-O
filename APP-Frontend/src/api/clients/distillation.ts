/**
 * distillation 域客户端：RADIX-Lite 蒸馏服务（/api/v1/distillation/*）。
 * 端点面对齐 CX-O-Frontend clients/distillation.ts。
 */
import { request } from '../base';

export type DistillationSourceType = 'text' | 'character_card' | 'image' | 'conversation_log';
export type DistillationGoal = 'memory' | 'agent' | 'memory_and_agent';
export type DistillationState =
  | 'S_INIT'
  | 'S_PREREAD'
  | 'S_QUESTION'
  | 'S_REFLECT'
  | 'S_CROSSVALIDATE'
  | 'S_EXTRACT'
  | 'S_STORAGE_DECISION'
  | 'S_FINALIZE'
  | 'S_REJECT';
export type AgentAction =
  | 'ask_user'
  | 'proceed'
  | 'reflect'
  | 'cross_validate'
  | 'extract'
  | 'decide'
  | 'finalize'
  | 'reject';

export interface StartDistillationRequest {
  source_type: DistillationSourceType;
  source_ref?: string;
  template_id: string;
  max_turns?: number;
  ask_user_on_ambiguity?: boolean;
}

export interface StartDistillationResponse {
  session_id: string;
  initial_state: string;
  preread_summary: string | null;
}

export interface AdvanceDistillationRequest {
  user_response?: string;
}

export interface AdvanceDistillationResponse {
  session_id: string;
  current_state: DistillationState;
  agent_action: AgentAction;
  next_needed: boolean;
  preread_summary?: string | null;
  ambiguity_questions?: string[];
  extracted_content?: string | null;
  quality_score?: number | null;
  turn_count?: number;
  message?: string;
}

export interface FinalizeDistillationRequest {
  override_decision?: string;
}

export interface FinalizeDistillationResponse {
  stored: boolean;
  location: 'memories' | 'permanent_memories' | 'rejected';
  memory_id: number | null;
  metadata: Record<string, unknown>;
  reason: string;
}

export interface SessionStatusResponse {
  session_id: string;
  source_type: DistillationSourceType;
  state: DistillationState;
  template_id: string;
  max_turns: number;
  ask_user_on_ambiguity: boolean;
  turns: Array<Record<string, unknown>>;
  preread_summary: string | null;
  ambiguity_questions: string[];
  extracted_content: string | null;
  quality_score: number | null;
  created_at: string;
  updated_at: string | null;
  finalized_at: string | null;
  is_finalized: boolean;
  error_message: string | null;
}

export interface BatchStartRequest {
  source_type: DistillationSourceType;
  source_ref: string;
  template_id: string;
  max_turns?: number;
  ask_user_on_ambiguity?: boolean;
  chunk_size?: number;
  distillation_goal: DistillationGoal;
  target_agent_id?: string;
}

export interface BatchSessionItem {
  session_id: string;
  chunk_index: number;
  chunk_preview: string;
  initial_state: string;
}

export interface BatchStartResponse {
  session_group_id: string;
  total_chunks: number;
  sessions: BatchSessionItem[];
  distillation_goal: DistillationGoal;
}

export interface GroupSessionStatus {
  session_id: string;
  chunk_index: number;
  state: DistillationState;
  is_finalized: boolean;
  extracted_content: string | null;
  quality_score: number | null;
}

export interface GroupStatusResponse {
  group_id: string;
  total_count: number;
  completed_count: number;
  sessions: GroupSessionStatus[];
}

export interface FinalizeAgentResponse {
  stored: boolean;
  location: string;
  memory_id: number | null;
  metadata: Record<string, unknown>;
  reason: string;
  agent_creation_result: {
    success: boolean;
    agent_id?: string;
    agent_name?: string;
    error?: string;
    character_card?: {
      name: string;
      description?: string;
    };
  };
}

export interface CharacterCardData {
  spec?: string;
  spec_version?: string;
  name: string;
  description?: string;
  personality?: string;
  scenario?: string;
  first_mes?: string;
  mes_example?: string;
  alternate_greetings?: string[];
  creator_notes?: string;
  system_prompt?: string;
  post_history_instructions?: string;
  character_book?: Record<string, unknown>;
  extensions?: Record<string, unknown>;
  extra_fields?: Record<string, unknown>;
}

export interface ParseCharacterCardResponse {
  status: string;
  character_card_data: CharacterCardData;
  source_ref: string;
  source_ref_length: number;
}

export const distillationApi = {
  /** 启动单次蒸馏会话 */
  startDistillation(data: StartDistillationRequest): Promise<StartDistillationResponse> {
    return request<StartDistillationResponse>({
      url: '/api/v1/distillation/start',
      method: 'post',
      data,
    });
  },

  /** 推进蒸馏状态机 */
  advanceDistillation(
    sessionId: string,
    data: AdvanceDistillationRequest,
  ): Promise<AdvanceDistillationResponse> {
    return request<AdvanceDistillationResponse>({
      url: `/api/v1/distillation/${encodeURIComponent(sessionId)}/advance`,
      method: 'post',
      data,
    });
  },

  /** 终结蒸馏会话（仅记忆蒸馏） */
  finalizeDistillation(
    sessionId: string,
    data: FinalizeDistillationRequest = {},
  ): Promise<FinalizeDistillationResponse> {
    return request<FinalizeDistillationResponse>({
      url: `/api/v1/distillation/${encodeURIComponent(sessionId)}/finalize`,
      method: 'post',
      data,
    });
  },

  /** 查询会话状态 */
  getSessionStatus(sessionId: string): Promise<SessionStatusResponse> {
    return request<SessionStatusResponse>({
      url: `/api/v1/distillation/${encodeURIComponent(sessionId)}`,
    });
  },

  /** 批量切分启动蒸馏（超长文本智能切分 + 多 session） */
  startBatchDistillation(data: BatchStartRequest): Promise<BatchStartResponse> {
    return request<BatchStartResponse>({
      url: '/api/v1/distillation/start-batch',
      method: 'post',
      data,
    });
  },

  /** 查询批量切分组状态 */
  getGroupStatus(groupId: string): Promise<GroupStatusResponse> {
    return request<GroupStatusResponse>({
      url: `/api/v1/distillation/group/${encodeURIComponent(groupId)}`,
    });
  },

  /** 终结并创建角色卡 agent */
  finalizeWithAgentCreation(
    sessionId: string,
    data: FinalizeDistillationRequest = {},
  ): Promise<FinalizeAgentResponse> {
    return request<FinalizeAgentResponse>({
      url: `/api/v1/distillation/${encodeURIComponent(sessionId)}/finalize-agent`,
      method: 'post',
      data,
    });
  },

  /** 解析 PNG 角色卡（文件上传） */
  parseCharacterCardFromFile(file: File): Promise<ParseCharacterCardResponse> {
    const formData = new FormData();
    formData.append('file', file);
    return request<ParseCharacterCardResponse>({
      url: '/api/v1/distillation/parse-character-card',
      method: 'post',
      data: formData,
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  /** 解析 JSON 角色卡（JSON 内容） */
  parseCharacterCardFromJson(jsonContent: string | object): Promise<ParseCharacterCardResponse> {
    return request<ParseCharacterCardResponse>({
      url: '/api/v1/distillation/parse-character-card',
      method: 'post',
      data: { json_content: jsonContent },
    });
  },
};
