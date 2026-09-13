/**
 * avatar-manifest 域客户端：头像可用动作/表情清单上报（spec enhance-emotion-tts-and-action-presets Task 5.2）。
 *
 * 前端头像 manifest 加载完成后，将可用动作名（motions keys）与表情 id 清单
 * 上报服务端会话级缓存（POST /api/avatar-manifest，覆盖式更新），供后续
 * 服务端提示词注入真实动作名（注入本身归 Task 4，本模块只做上报）。
 *
 * 设计口径：
 * - data 用 snake_case（agent_id）对齐后端契约（与 vision.ts filterFrame 同先例）；
 * - 空 actions 不上报（选择口径：避免空清单覆盖服务端有用缓存；重启后由下次
 *   manifest 就绪的上报自然恢复，无需上报空清单做清理）；
 * - 上报失败静默（console.warn），绝不影响头像加载主流程。
 */
import { request } from '../base';
import type { AvatarManifest } from '../../avatar/types';

export interface ReportAvatarManifestParams {
  agentId: string;
  actions: string[];
  expressions?: string[];
}

export interface ReportAvatarManifestResult {
  status: string;
  agent_id: string;
  actions_count: number;
  expressions_count: number;
  updated_at: string;
}

/** 上报该 agent 的可用动作/表情清单（覆盖式更新；调用方自行处理失败静默） */
export function reportAvatarManifest(
  params: ReportAvatarManifestParams,
): Promise<ReportAvatarManifestResult> {
  const data: Record<string, unknown> = {
    agent_id: params.agentId,
    actions: params.actions,
  };
  // expressions 省略时不下发该字段（后端缺省为空清单）
  if (params.expressions !== undefined) {
    data.expressions = params.expressions;
  }
  return request<ReportAvatarManifestResult>({
    url: '/api/avatar-manifest',
    method: 'post',
    data,
  });
}

/**
 * 从就绪的 AvatarManifest 提取可用动作/表情清单并上报服务端。
 *
 * 上报触发口径（spec「动作清单上报与注入」）：manifest 就绪即上报；
 * 重复加载/切换头像时 manifest 变化会重新调用本函数覆盖服务端缓存。
 *
 * 容错约定：
 * - manifest 缺失或 actions（motions keys）为空时跳过上报，不下发空清单
 *   （避免覆盖服务端有用缓存）；
 * - 上报失败仅 console.warn，不向调用方抛错——绝不影响头像加载主流程。
 */
export async function reportManifestActions(
  manifest: AvatarManifest | null | undefined,
  agentId: string | null | undefined,
): Promise<void> {
  if (!manifest || !agentId) return;
  // 可用动作名 = motions keys；可用表情 id = expressions[].id
  const actions = Object.keys(manifest.motions ?? {});
  if (actions.length === 0) return; // 空清单不上报：避免覆盖服务端有用缓存（口径见文件头注释）
  const expressions = (manifest.expressions ?? []).map((e) => e.id);
  try {
    await reportAvatarManifest({ agentId, actions, expressions });
  } catch (err) {
    // 静默降级：上报失败不影响头像加载主流程（服务端未上报时提示词安全回退）
    console.warn('[avatarManifest] 动作清单上报失败（不影响头像加载）:', err);
  }
}
