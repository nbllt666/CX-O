/**
 * API 公共类型：与 CX-O 后端响应契约对齐。
 * 域专属类型（graph 节点 / voiceworkstation）在各自客户端模块内定义。
 */

export interface Agent {
  id: string;
  name: string;
  description?: string;
  is_default?: boolean;
  model?: string;
  memory_scene?: string;
  tools?: string[];
  capabilities?: string[];
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number;
  use_memory?: boolean;
  use_tools?: boolean;
  decay_model?: string;
  vision_enabled?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface HealthStatus {
  status: string;
  version?: string;
  components?: Record<string, boolean>;
  timestamp?: string;
  database?: { status: string };
  memory?: { status: string };
  vector_store?: { status: string };
}

export interface GraphStats {
  node_count: number;
  edge_count: number;
  graph_enabled: boolean;
  avg_degree?: number;
  graph_density?: number;
  node_types?: string[];
  edge_types?: string[];
  connected?: boolean;
  libraries?: Record<string, { entity_count: number; relation_count: number }>;
  database_path?: string;
  message?: string;
}

export interface AcpStats {
  total_agents: number;
  active_agents: number;
  total_messages: number;
  total_conversations?: number;
  avg_response_time?: number;
}

export interface AcpAgentRow {
  id: string;
  name: string;
  description?: string;
  capabilities?: string[];
  status?: string;
}

/** ACP 消息：与后端 ACPMessageInfo.to_dict() 字段对齐 */
export interface AcpMessage {
  id: string;
  type: string;
  from_agent_id: string;
  from_agent_name: string;
  to_agent_id: string | null;
  to_group_id: string | null;
  content: Record<string, unknown> | string;
  timestamp: string;
  is_read: boolean;
  is_sent: boolean;
  metadata: Record<string, unknown>;
}

export interface ArchiveStats {
  total_memories: number;
  archived_memories: number;
  active_memories: number;
  total_archived?: number;
  merge_count?: number;
  duplicate_count?: number;
  archive_level_counts?: Record<string, number>;
}

export interface ToolStats {
  total_tools: number;
  enabled_tools: number;
  builtin_tools: number;
  custom_tools: number;
  active_tools?: number;
  mcp_tools?: number;
  total_calls?: number;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  type: 'builtin' | 'custom' | 'mcp' | 'cxfc';
  status: 'active' | 'inactive' | 'error';
  config: Record<string, unknown>;
  icon?: string;
  created_at: string;
  last_used?: string;
  use_count: number;
  parameters?: Record<string, unknown>;
  examples?: string[];
  tags?: string[];
  source_plugin_id?: string;
}

export interface CxfcPlugin {
  plugin_id: string;
  host?: string;
  port?: number;
  name?: string;
  version?: string;
  capabilities: string[];
  status: 'connected' | 'disconnected';
  transport?: 'direct' | 'relay' | 'embedded';
  last_seen?: string | null;
  tools: Array<{ name: string; description?: string }>;
  skills: Array<{ name: string; description?: string }>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CxfcSkill {
  name: string;
  description?: string;
  prompt_template?: string;
  trigger_keywords: string[];
  trigger_events: string[];
  auto_inject: boolean;
  source_plugin_id: string;
}

export interface CxfcDiscoveredPlugin {
  host: string;
  port: number;
  name?: string;
  capabilities: string[];
  version?: string;
}

export interface FrontendLimits {
  max_upload_size_mb: number;
  max_chat_images: number;
  avatar_min_width: number;
  avatar_max_width: number;
  temperature_max: number;
  speed_max: number;
}

export interface GraphEntity {
  id: string;
  type: string;
  name?: string;
  properties?: Record<string, unknown>;
  created_at?: string;
}

export interface GraphRelation {
  id: string;
  type: string;
  source_id: string;
  target_id: string;
  properties?: Record<string, unknown>;
  created_at?: string;
}

export interface VectorData {
  memory_id: number;
  content: string;
  memory_type: string;
  importance: number;
  created_at: string;
  has_vector: boolean;
}

export interface DuplicateGroup {
  group_id: string;
  memory_ids: number[];
  canonical_id: number;
  similarity_matrix: Record<string, number>;
}

export interface ArchiveResult {
  archived_count: number;
  merged_count: number;
  errors?: string[];
  results?: {
    archived?: unknown[];
    merged?: unknown[];
  };
}

export interface Memory {
  id: number;
  content: string;
  type: string;
  importance: number;
  tags: string[];
  created_at: string;
  is_archived: boolean;
  archived_at?: string;
  emotion_score?: number;
  metadata?: Record<string, unknown>;
}

export interface Session {
  id: string;
  title: string;
  agent_id: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
  session_id?: string;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface AvatarInfo {
  id: string;
  name: string;
  type: string;
  size: number;
  created_at: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
}

/** CX-O-Autonomy 四维动机（0-1，对齐 autonomy_state.schema.json / Motivations） */
export interface AutonomyMotivations {
  curiosity: number;
  social_need: number;
  creative_drive: number;
  fatigue: number;
}

/** 自主系统状态快照（对齐 autonomy_state.schema.json） */
export type AutonomyStatus = AutonomyStatusDisabled | AutonomyStatusActive;

/** 未启用/未装配：后端返回 {"status": "disabled"}（HTTP 200，不抛错） */
export interface AutonomyStatusDisabled {
  status: 'disabled';
}

/** 已启用：含动机/状态/上次行动/预算等字段 */
export interface AutonomyStatusActive {
  status: 'running' | 'paused' | 'sleeping' | 'budget_limited' | 'error';
  motivations?: AutonomyMotivations;
  last_action?: string | null;
  last_cycle_at?: string | null;
  daily_budget_used_tokens?: number;
  budget_reset_date?: string | null;
  diary_last_at?: string | null;
}

/** 控制指令响应（POST /api/autonomy/control） */
export interface AutonomyControlResult {
  status: string;
  state: {
    enabled: boolean;
    running: boolean;
    status: string;
  };
}

/** 审计日志条目（对齐 autonomy_audit.schema.json） */
export interface AutonomyAuditEntry {
  timestamp: string;
  action: string;
  target?: string;
  payload?: Record<string, unknown>;
  result?: 'success' | 'failed' | 'blocked' | 'skipped';
  error?: string | null;
  cost_tokens?: number;
  trigger_reason?: string;
  expected_outcome?: string;
  motivations?: AutonomyMotivations;
  [key: string]: unknown;
}

/** 自主系统配置（对齐 autonomy_config.schema.json / config.py AutonomyConfig） */
export interface AutonomyConfig {
  enabled: boolean;
  auto_start: boolean;
  agent_id: string;
  loop_interval_minutes: number;
  rss_sources: string[];
  search: {
    mcp_server_name: string;
    fallback_rss: boolean;
  };
  schedule: {
    wake_time: string;
    sleep_time: string;
    golden_start: string;
    golden_end: string;
    diary_time: string;
    quiet_windows: string[];
  };
  budget: {
    daily_token_limit: number;
    daily_llm_calls_limit: number;
    cost_alert_threshold: number;
    overspend_mode: 'sleep' | 'low_cost';
  };
  platforms: string[];
  permissions: {
    allowed_actions: string[];
    blocked_actions: string[];
  };
  safety: {
    content_gate_enabled: boolean;
    persona_check_enabled: boolean;
    post_rate_per_hour: number;
    user_online_sleep: boolean;
    leave_mode_authorize: boolean;
  };
  store_path: string;
}

// ── CX-O-Dream 梦境引擎类型（对齐 server/autonomy/dream/ 契约） ──

/** 梦境引擎状态快照（对齐 dream_status 契约） */
export type DreamStatus = DreamStatusDisabled | DreamStatusActive;

/** 未启用/未装配：后端返回 {"status": "disabled"}（HTTP 200，不抛错） */
export interface DreamStatusDisabled {
  status: 'disabled';
}

/** 已启用：含运行态/启用标记/上次会话/会话统计 */
export interface DreamStatusActive {
  status: 'idle' | 'dreaming' | 'purge_scheduled';
  enabled: boolean;
  last_session_at?: string | null;
  stats?: DreamStats;
}

/** 梦境会话统计（engine._stats：sessions/generated/approved/rejected/purges） */
export interface DreamStats {
  sessions: number;
  generated: number;
  approved: number;
  rejected: number;
  purges: number;
}

/** 梦境缓冲候选（对齐 dream_buffer 行，固化前只进缓冲不写主库） */
export interface DreamBufferEntry {
  id: number;
  dream_session_id: string;
  candidate_content: string;
  lucidity_score: number;
  decision: 'pending' | 'approved' | 'rejected';
  associated_entities?: string[] | null;
  associated_memories?: string[] | null;
  created_at: string;
  expires_at: string;
  decision_reason?: string | null;
  emotion_shift?: Record<string, unknown> | null;
  agent_id?: string;
}

/** 梦境候选列表分页响应：{"items": [...], "total": int} */
export interface DreamListResult {
  items: DreamBufferEntry[];
  total: number;
}

/** 梦境会话触发结果（POST /api/dream/trigger；未启用返回 {"status": "disabled"}） */
export type DreamTriggerResult =
  | { status: 'disabled' }
  | { generated: number; approved: number; rejected: number };

/** 梦境确认结果（POST /api/dream/{id}/confirm → 固化主库） */
export interface DreamConfirmResult {
  memory_id: number;
}

/** 梦境否定结果（POST /api/dream/{id}/reject → 缓冲置 rejected，不写主库） */
export interface DreamRejectResult {
  status: string;
  buffer_id: number;
}

/** 按会话回滚结果（DELETE /api/dream/session/{session_id}，红线 R5） */
export interface DreamPurgeSessionResult {
  purged: number;
}

/** 手动清除任务结果（POST /api/dream/purge） */
export interface DreamPurgeResult {
  purged_memories: number;
  purged_buffer: number;
}

/** 梦境引擎配置（对齐 DreamConfig / dream_config.schema.json；schedule 复用 ScheduleConfig） */
export interface DreamConfig {
  enabled: boolean;
  model: string;
  dream_temperature: number;
  candidates_per_session: number;
  material_window_days: number;
  max_material_items: number;
  min_lucidity: number;
  dream_ttl_hours: number;
  purge_threshold: number;
  confirmed_importance: number;
  surface_on_wake: boolean;
  surface_probability: number;
  max_surface_per_day: number;
  schedule: {
    wake_time: string;
    sleep_time: string;
    golden_start: string;
    golden_end: string;
    diary_time: string;
    quiet_windows: string[];
  };
}
