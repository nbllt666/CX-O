/**
 * per-agent 形象绑定（agent_id → 形象偏好）。
 *
 * 让每个桌宠 Agent 可独立选择自己的 VRM / Live2D 形象（桌宠多开时不同 agent
 * 显示不同模型）。绑定仅存在于前端 localStorage（跨同 session 窗口共享，桌宠
 * 多开各窗可读到同一份绑定），不写入后端 agents.json——形象是渲染层概念，
 * 后端无 per-agent avatar 契约，避免触碰 public/ 保护。
 *
 * 内存结构：{ [agentId]: { type: 'vrm' | 'live2d' | 'none'; modelPath?: string } }
 *  - type='vrm'/'live2d'：该 agent 固定用对应引擎；不提供 modelPath 时用全局默认模型。
 *  - type='none'：该 agent 不显示形象。
 *
 * 读取优先级：绑定存在则以绑定为准；否则回落到全局设置（原行为）。
 */
import type { AvatarType } from '../store/settingsStore';

export const AGENT_AVATAR_BINDINGS_KEY = 'cxo-agent-avatar-bindings';

export interface AgentAvatarBinding {
  type: AvatarType;
  /** 可选：覆盖该 agent 的形象模型路径（缺省用全局默认模型） */
  modelPath?: string;
}

type BindingTable = Record<string, AgentAvatarBinding>;

function readTable(): BindingTable {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(AGENT_AVATAR_BINDINGS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as BindingTable;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeTable(table: BindingTable): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(AGENT_AVATAR_BINDINGS_KEY, JSON.stringify(table));
  } catch {
    // 持久化异常静默忽略（仅影响形象偏好记忆，不阻断桌宠渲染）
  }
}

export function getAgentAvatarBindings(): BindingTable {
  return readTable();
}

export function getAgentAvatarBinding(agentId: string): AgentAvatarBinding | null {
  return readTable()[agentId] ?? null;
}

export function setAgentAvatarBinding(agentId: string, binding: AgentAvatarBinding): void {
  const table = readTable();
  table[agentId] = binding;
  writeTable(table);
}

export function clearAgentAvatarBinding(agentId: string): void {
  const table = readTable();
  if (agentId in table) {
    delete table[agentId];
    writeTable(table);
  }
}