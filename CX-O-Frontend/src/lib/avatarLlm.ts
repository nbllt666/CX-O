import type {
  AvatarManifest,
  ExpressionId,
  ExpressionLayer,
  ParameterOverride,
} from '../components/Avatar/avatarManifest';
import {
  getAvatarExpression,
  getAvatarNeutralExpressionId,
  getAvatarParameterControl,
  hasAvatarExpression,
} from '../components/Avatar/avatarManifest';

export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  expression?: ExpressionId;
  expressionMix?: ExpressionLayer[];
  parameterOverrides?: ParameterOverride[];
  meta?: string;
};

export type AssistantResponse = {
  reply: string;
  expression: ExpressionId;
  expressionMix: ExpressionLayer[];
  parameterOverrides: ParameterOverride[];
  intensity: number;
  durationMs: number;
  source: 'remote';
};

type CreateAssistantResponseArgs = {
  avatar: AvatarManifest;
  history: ChatMessage[];
  systemPrompt: string;
};

type RemoteMessage = {
  role: 'system' | 'user' | 'assistant';
  content: string;
};

export type LlmSettings = {
  apiUrl: string;
  apiKey: string;
  model: string;
};

type RawExpressionLayer = {
  expression?: string;
  key?: string;
  weight?: number;
};

type RawParameterOverride = {
  id?: string;
  key?: string;
  parameter?: string;
  value?: number;
};

type ParsedTag = {
  type: string;
  params: string[];
};

const llmSettingsStorageKey = 'cxo:avatar-llm-settings';

const KNOWN_TAG_TYPES = new Set(['emotion', 'blend', 'bone', 'pose', 'release', 'wind', 'sleep']);

export class LlmConfigurationError extends Error {
  code = 'llm_configuration_missing' as const;
}

export class LlmConnectionError extends Error {
  code = 'llm_connection_failed' as const;
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

export class LlmResponseFormatError extends Error {
  code = 'llm_response_invalid_format' as const;
}

function clampWeight(value: number) {
  return Math.min(Math.max(value, 0), 1);
}

function normalizeExpressionId(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, '_');
}

function clampExpression(value: string, avatar: AvatarManifest): ExpressionId {
  const normalizedValue = normalizeExpressionId(value);

  if (hasAvatarExpression(avatar, normalizedValue)) {
    return normalizedValue;
  }

  return getAvatarNeutralExpressionId(avatar);
}

function parseTags(text: string): { tags: ParsedTag[]; cleanText: string } {
  const tags: ParsedTag[] = [];
  const cleanText = text.replace(/\[([^\]]+)\]/g, (match, content: string) => {
    const parts = content.split(':');
    if (parts.length > 0 && KNOWN_TAG_TYPES.has(parts[0])) {
      tags.push({ type: parts[0], params: parts.slice(1) });
      return '';
    }
    return match;
  }).replace(/\s{2,}/g, ' ').trim();
  return { tags, cleanText };
}

/** @deprecated Use tag-based parsing instead of JSON extraction. */
function stripMarkdownFence(raw: string) {
  return raw.replace(/^```json\s*/i, '').replace(/^```\s*/i, '').replace(/\s*```$/i, '').trim();
}

/** @deprecated Use tag-based parsing instead of JSON extraction. */
function stripAvatarStateMarkers(raw: string) {
  return raw.replace(/\s*\[avatar_state[^\]]*\]/gi, '').trim();
}

function sortExpressionMix(layers: ExpressionLayer[]) {
  return [...layers].sort((left, right) => right.weight - left.weight);
}

/** @deprecated Use tag-based parsing instead of JSON extraction. */
function formatHistoryState(avatar: AvatarManifest, expressionMix: ExpressionLayer[] | undefined) {
  if (!expressionMix?.length) {
    return '';
  }

  return expressionMix
    .map((layer) => {
      const expressionItem = getAvatarExpression(avatar, layer.key);
      const kind = expressionItem?.kind ?? 'emotion';
      return `${layer.key}:${kind}:${layer.weight.toFixed(2)}`;
    })
    .join(', ');
}

/** @deprecated Use tag-based parsing instead of JSON extraction. */
function extractJsonObject(raw: string) {
  const trimmed = stripAvatarStateMarkers(stripMarkdownFence(raw));
  const firstBrace = trimmed.indexOf('{');
  const lastBrace = trimmed.lastIndexOf('}');

  if (firstBrace === -1 || lastBrace === -1 || lastBrace <= firstBrace) {
    return null;
  }

  return trimmed.slice(firstBrace, lastBrace + 1);
}

/** @deprecated Use tag-based parsing instead of JSON extraction. */
export function parseAssistantPayload(raw: string) {
  const jsonCandidate = extractJsonObject(raw);

  if (!jsonCandidate) {
    return null;
  }

  try {
    return JSON.parse(jsonCandidate) as Partial<AssistantResponse> & {
      expressionMix?: RawExpressionLayer[];
      parameterOverrides?: RawParameterOverride[];
    };
  } catch {
    return null;
  }
}

function clampParameterValue(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

/** @deprecated Use tag-based parsing instead of JSON extraction. */
export function normalizeParameterOverrides(
  avatar: AvatarManifest,
  rawOverrides: RawParameterOverride[] | ParameterOverride[] | undefined,
) {
  const normalized = new Map<string, number>();

  for (const rawOverride of rawOverrides ?? []) {
    const parameterId =
      ('parameter' in rawOverride ? rawOverride.parameter : undefined)
      ?? rawOverride.id
      ?? ('key' in rawOverride ? rawOverride.key : undefined);

    if (!parameterId || typeof rawOverride.value !== 'number') {
      continue;
    }

    const parameterControl = getAvatarParameterControl(avatar, parameterId);
    if (!parameterControl) {
      continue;
    }

    normalized.set(
      parameterId,
      clampParameterValue(rawOverride.value, parameterControl.min, parameterControl.max),
    );
  }

  return [...normalized.entries()].map(([id, value]) => ({
    id,
    value,
  }));
}

/** @deprecated Use tag-based parsing instead of JSON extraction. */
export function normalizeExpressionMix(
  avatar: AvatarManifest,
  rawLayers: RawExpressionLayer[] | ExpressionLayer[] | undefined,
  fallbackExpression = getAvatarNeutralExpressionId(avatar),
): ExpressionLayer[] {
  const layers = rawLayers
    ?.map((layer) => {
      const expressionId =
        ('expression' in layer ? layer.expression : undefined) ?? layer.key ?? fallbackExpression;
      const key = clampExpression(expressionId, avatar);
      const expressionItem = getAvatarExpression(avatar, key);
      const normalizedWeight = clampWeight(layer.weight ?? 0);
      return {
        key,
        weight: expressionItem?.kind && expressionItem.kind !== 'emotion' && normalizedWeight > 0
          ? 1
          : normalizedWeight,
      };
    })
    .filter((layer) => layer.weight > 0.02);

  const merged = new Map<ExpressionId, number>();

  for (const layer of layers ?? []) {
    merged.set(layer.key, Math.min(1, (merged.get(layer.key) ?? 0) + layer.weight));
  }

  const normalized = sortExpressionMix(
    [...merged.entries()].map(([key, weight]) => ({
      key,
      weight,
    })),
  ).slice(0, 3);

  if (normalized.length > 0) {
    return normalized;
  }

  return [{ key: clampExpression(fallbackExpression, avatar), weight: 1 }];
}

export function getPrimaryExpression(
  avatar: AvatarManifest,
  expressionMix: ExpressionLayer[],
): ExpressionId {
  return expressionMix[0]?.key ?? getAvatarNeutralExpressionId(avatar);
}

export { getAvatarNeutralExpressionId };

export function getDefaultLlmSettings(): LlmSettings {
  return {
    apiUrl: import.meta.env.VITE_LLM_API_URL ?? '',
    apiKey: import.meta.env.VITE_LLM_API_KEY ?? '',
    model: import.meta.env.VITE_LLM_MODEL ?? '',
  };
}

export function loadStoredLlmSettings(): LlmSettings {
  const fallback = getDefaultLlmSettings();

  if (typeof window === 'undefined') {
    return fallback;
  }

  try {
    const raw = window.localStorage.getItem(llmSettingsStorageKey);
    if (!raw) {
      return fallback;
    }

    const parsed = JSON.parse(raw) as Partial<LlmSettings>;
    return {
      apiUrl: parsed.apiUrl?.trim() || fallback.apiUrl,
      apiKey: parsed.apiKey?.trim() || fallback.apiKey,
      model: parsed.model?.trim() || fallback.model,
    };
  } catch {
    return fallback;
  }
}

export function saveStoredLlmSettings(settings: LlmSettings) {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.setItem(
    llmSettingsStorageKey,
    JSON.stringify({
      apiUrl: settings.apiUrl.trim(),
      apiKey: settings.apiKey.trim(),
      model: settings.model.trim(),
    }),
  );
}

export function hasUsableLlmSettings(settings: LlmSettings) {
  return Boolean(settings.apiUrl && settings.apiKey && settings.model);
}

/** @deprecated Use tag-based parsing instead of JSON extraction. */
export function getOngoingAvatarState(avatar: AvatarManifest, history: ChatMessage[]) {
  const latestAssistantMessage = [...history].reverse().find(
    (message) => message.role === 'assistant' && message.expressionMix?.length,
  );

  return formatHistoryState(avatar, latestAssistantMessage?.expressionMix);
}

async function fetchRemoteCompletion(
  apiUrl: string,
  apiKey: string,
  model: string,
  messages: RemoteMessage[],
  temperature: number,
) {
  const normalizedModel = model.trim().toLowerCase();
  const shouldDisableThinking = normalizedModel.startsWith('qwen')
    && !normalizedModel.includes('thinking');

  const response = await fetch(apiUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature,
      max_tokens: 400,
      ...(shouldDisableThinking
        ? {
            enable_thinking: false,
            extra_body: {
              enable_thinking: false,
            },
          }
        : {}),
      messages,
    }),
  });

  if (!response.ok) {
    throw new LlmConnectionError(`Remote LLM failed with ${response.status}`, response.status);
  }

  const payload = (await response.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };

  return payload.choices?.[0]?.message?.content ?? '';
}

async function requestRemoteAssistant({
  avatar,
  history,
  systemPrompt,
}: CreateAssistantResponseArgs): Promise<AssistantResponse> {
  const settings = loadStoredLlmSettings();
  const apiUrl = settings.apiUrl;
  const apiKey = settings.apiKey;
  const model = settings.model;

  if (!hasUsableLlmSettings(settings)) {
    throw new LlmConfigurationError(
      'LLM settings are incomplete. Please open LLM Settings and fill API URL, Model, and API Key.',
    );
  }

  const baseMessages: RemoteMessage[] = [
    { role: 'system', content: systemPrompt },
    ...history.map((message) => ({
      role: message.role,
      content: message.content,
    })),
  ];

  let content = await fetchRemoteCompletion(apiUrl, apiKey, model, baseMessages, 0.8);

  if (!content.trim()) {
    const retryMessages: RemoteMessage[] = [
      ...baseMessages,
      {
        role: 'system',
        content: 'Your previous output was empty. Please respond again with natural text and control tags.',
      },
    ];
    content = await fetchRemoteCompletion(apiUrl, apiKey, model, retryMessages, 0.2);
  }

  if (!content.trim()) {
    throw new LlmResponseFormatError('Remote LLM returned an empty response.');
  }

  const { tags, cleanText } = parseTags(content);

  const emotionTags = tags.filter((t) => t.type === 'emotion');
  const blendTags = tags.filter((t) => t.type === 'blend');

  const lastEmotion = emotionTags.length > 0
    ? emotionTags[emotionTags.length - 1].params[0]
    : undefined;

  const expressionId = lastEmotion
    ? clampExpression(lastEmotion, avatar)
    : getAvatarNeutralExpressionId(avatar);

  const layers: ExpressionLayer[] = [{ key: expressionId, weight: 1 }];
  const parameterOverrides: ParameterOverride[] = [];

  for (const blend of blendTags) {
    const name = blend.params[0];
    const rawWeight = blend.params[1] ? parseFloat(blend.params[1]) : 0.5;
    const normalizedId = normalizeExpressionId(name);
    if (hasAvatarExpression(avatar, normalizedId)) {
      layers.push({ key: normalizedId, weight: clampWeight(rawWeight) });
    } else {
      const control = getAvatarParameterControl(avatar, name);
      if (control) {
        parameterOverrides.push({
          id: name,
          value: clampParameterValue(rawWeight, control.min, control.max),
        });
      }
    }
  }

  const expressionMix = sortExpressionMix(layers).slice(0, 3);

  return {
    reply: cleanText || '...',
    expression: getPrimaryExpression(avatar, expressionMix),
    expressionMix,
    parameterOverrides,
    intensity: 0.65,
    durationMs: 2800,
    source: 'remote',
  };
}

export function createSystemPrompt(avatar: AvatarManifest) {
  const isVrm = avatar.avatarType === 'vrm';
  const avatarDescriptor = isVrm ? 'VRM 3D avatar' : 'Live2D avatar';

  const expressionCatalog = avatar.expressions
    .map((e) => `- id: "${e.id}", kind: "${e.kind}", label: "${e.label}", meaning: "${e.prompt}"`)
    .join('\n');

  const boneCatalog = isVrm && avatar.boneControls?.length
    ? avatar.boneControls
        .map((b) => `- id: "${b.id}", label: "${b.label}", range: x[${b.rotationRange.x}] y[${b.rotationRange.y}] z[${b.rotationRange.z}], meaning: "${b.prompt}"`)
        .join('\n')
    : undefined;

  const parameterCatalog = !isVrm && avatar.parameterControls?.length
    ? avatar.parameterControls
        .map((p) => `- id: "${p.id}", label: "${p.label}", range: [${p.min}, ${p.max}], meaning: "${p.prompt}"`)
        .join('\n')
    : undefined;

  const personaTraits = avatar.persona.traits.join(', ');
  const personaRules = avatar.persona.styleRules.map((rule) => `- ${rule}`).join('\n');

  const lines: string[] = [
    `You are controlling the ${avatarDescriptor} ${avatar.name}.`,
    `Persona tone: ${avatar.persona.tone}.`,
    `Persona traits: ${personaTraits}.`,
    'Style rules:',
    personaRules,
    '',
    'You control the avatar by embedding control tags in your response text.',
    'Tag format: [tagType:param1:param2:...]',
    '',
    'Available tag types:',
    '- [emotion:name] — Switch emotion expression. Examples: [emotion:happy], [emotion:sad], [emotion:angry], [emotion:surprised], [emotion:relaxed], [emotion:neutral]',
    '- [blend:name:weight] — Direct BlendShape control, weight 0-1. Examples: [blend:Happy:0.3], [blend:Blink:0.5]',
  ];

  if (isVrm) {
    lines.push(
      '- [bone:name:rx:ry:rz] or [bone:name:rx:ry:rz:speed] — Bone rotation in radians, speed 0.1-5.0. Example: [bone:head:0.2:0.3:0:0.5]',
      '- [pose:durationMs] — Hold current pose for duration. Example: [pose:3000]. Default 3000ms.',
      '- [release] — Release held pose.',
      '- [wind:direction:strength:gustStrength:gustFrequency:gustDuration] — Wind effect, direction 0-360°, strength 0-1. Example: [wind:90:0.5:0.3:2.0:1.5]',
    );
  }

  lines.push(
    '- [sleep:ms] — TTS pause in milliseconds. Example: [sleep:500]',
    '',
    'Expression catalog (only use ids from this list):',
    expressionCatalog,
  );

  if (isVrm && boneCatalog) {
    lines.push(
      '',
      'Bone control catalog (only use ids from this list):',
      boneCatalog,
    );
  }

  if (!isVrm && parameterCatalog) {
    lines.push(
      '',
      'Parameter control catalog (only use ids from this list):',
      parameterCatalog,
    );
  }

  lines.push(
    '',
    'How to use tags for time-synced control:',
    '- Place tags before the text they should accompany.',
    '- Use [sleep:ms] for pauses in speech.',
    ...(isVrm ? ['- Use [pose:durationMs] to hold a body position.'] : []),
    '- Combine multiple [blend:...] tags for subtle expressions.',
    '',
    'Respond in natural text with embedded tags. Do NOT use JSON format.',
    'Tags are hidden from the user (stripped before display).',
    '',
    'Example:',
  );

  if (isVrm) {
    lines.push(
      '[emotion:happy]你好！[blend:Happy:0.5]很高兴见到你！[sleep:300][bone:head:0.1:0.2:0:0.5]咦？[pose:2000]让我想想...',
    );
  } else {
    lines.push(
      '[emotion:happy]你好！[blend:ParamMouthOpenY:0.3]很高兴见到你！[sleep:300]嗯...',
    );
  }

  return lines.join('\n');
}

export async function createAssistantResponse(
  args: CreateAssistantResponseArgs,
): Promise<AssistantResponse> {
  return requestRemoteAssistant(args);
}
