/**
 * character-host.tsx — 角色立绘宿主组件
 *
 * 模块: 模块5 二次元元素层
 * 对应 I4 frontend_anime.pyi §CharacterHost:
 *   - props: { page, position, zIndex, staticFallback }
 *   - 根据 page 选择嵌入方式（6 页面差异化策略）
 *   - 根据 position 决定立绘位置和尺寸
 *   - z-index=5（角色立绘层 OBS-H）
 *   - 资产加载失败时降级到纯色占位（梦境紫/星海青）+ 控制台输出 FE-ANI-002
 *
 * 6 页面嵌入策略（D4 §characterEmbedding.pages）:
 *   1. Dashboard: 侧边静态立绘（PNG/WebP，1x/2x/3x srcset）
 *   2. Chat: 角色头像（圆形，96px）+ 输入框旁小立绘
 *   3. AudioWorkstation: 顶部装饰条带（半透明角色剪影）
 *   4. Live: 完整 Live2D 交互（占位容器，由调用方填充）
 *   5. Pet: 完整 PetAvatar 交互（占位容器，由调用方填充）
 *   6. Agents/Acp/Settings: 不嵌入角色（保持工具属性）
 *
 * 跨模块导入约束: 不直接 import Live2D/PetAvatar（属模块7/8），
 *   Live/Pet 页面仅提供占位容器，由调用方填充实际组件。
 *
 * @version 1.0.0
 */

import {
  useState,
  type CSSProperties,
  type ReactElement,
} from 'react';
import {
  ANI_ERROR_CODES,
  ANIME_PALETTE,
  CharacterAssetError,
  Z_INDEX_LAYERS,
  type CharacterHostProps,
  type CharacterPage,
  type CharacterPosition,
} from './anime-palette';

/** 降级占位色（梦境紫，闭合判据第13项） */
const FALLBACK_COLOR = ANIME_PALETTE.dreamPurple;
/** 备用降级色（星海青） */
const FALLBACK_COLOR_ALT = ANIME_PALETTE.starSeaCyan;

/** 各页面的默认资产路径前缀（约定路径，调用方可通过 staticFallback 覆盖） */
const DEFAULT_ASSET_PATHS: Record<CharacterPage, { base: string; width: number; height: number }> = {
  dashboard: { base: '/assets/character/standee', width: 200, height: 400 },
  chat: { base: '/assets/character/avatar', width: 96, height: 96 },
  audiowstation: { base: '/assets/character/silhouette', width: 320, height: 60 },
  live: { base: '/assets/character/live2d', width: 400, height: 600 },
  pet: { base: '/assets/character/petavatar', width: 120, height: 120 },
};

/**
 * 角色立绘宿主组件。
 *
 * 对应 I4 frontend_anime.pyi §CharacterHost。
 *
 * 实现细节:
 *   - 根据 page 选择嵌入方式（dashboard=sidebar / chat=avatar / audiowstation=topbar-deco / live/pet=full-interactive）
 *   - 根据 position 决定立绘位置和尺寸
 *   - 静态立绘提供 1x/2x/3x srcset
 *   - z-index=5（角色立绘层 OBS-H）
 *   - 资产加载失败时降级到纯色占位 + 控制台输出 FE-ANI-002
 *
 * 立绘不主导 UI 结构（B 路径核心约束）:
 *   - 角色作为视觉锚点出现在非核心区域（侧边/顶部装饰）
 *   - 不占据主内容区，不驱动布局决策
 *
 * @param props 角色立绘配置
 * @returns 渲染后的角色立绘宿主
 */
export function CharacterHost(props: CharacterHostProps): ReactElement {
  const { page, position, zIndex, staticFallback } = props;

  // z-index 校验（OBS-H: 角色立绘=5）
  const effectiveZIndex = zIndex === Z_INDEX_LAYERS.character ? zIndex : Z_INDEX_LAYERS.character;

  // 根据 page 渲染对应策略
  switch (page) {
    case 'dashboard':
      return <StaticStandee position={position} zIndex={effectiveZIndex} staticFallback={staticFallback} page={page} />;
    case 'chat':
      return <ChatAvatar position={position} zIndex={effectiveZIndex} staticFallback={staticFallback} page={page} />;
    case 'audiowstation':
      return <TopbarDecoration position={position} zIndex={effectiveZIndex} staticFallback={staticFallback} page={page} />;
    case 'live':
      return <InteractiveSlot position={position} zIndex={effectiveZIndex} page={page} label="Live2D" />;
    case 'pet':
      return <InteractiveSlot position={position} zIndex={effectiveZIndex} page={page} label="PetAvatar" />;
    default:
      // Agents/Acp/Settings 不嵌入角色（D4 §characterEmbedding.pages 第 6 项）
      return <div data-character-host="none" data-page={page} style={{ display: 'none' }} />;
  }
}

// =============================================================================
// 子组件：Dashboard 侧边静态立绘
// =============================================================================

interface StaticStandeeProps {
  position: CharacterPosition;
  zIndex: number;
  staticFallback?: string | null;
  page: CharacterPage;
}

/** Dashboard 侧边静态立绘（PNG/WebP，1x/2x/3x srcset） */
function StaticStandee(props: StaticStandeeProps): ReactElement {
  const { position, zIndex, staticFallback, page } = props;
  const [loadFailed, setLoadFailed] = useState(false);
  const assetConfig = DEFAULT_ASSET_PATHS[page];
  const basePath = staticFallback ?? assetConfig.base;

  const style: CSSProperties = {
    position: 'absolute',
    [position === 'sidebar' ? 'right' : 'left']: 0,
    bottom: 0,
    width: assetConfig.width,
    height: assetConfig.height,
    zIndex,
    pointerEvents: 'none',
  };

  if (loadFailed) {
    return <FallbackPlaceholder style={style} />;
  }

  return (
    <div data-character-host="dashboard" style={style}>
      <img
        src={`${basePath}-1x.png`}
        srcSet={`${basePath}-1x.png 1x, ${basePath}-2x.png 2x, ${basePath}-3x.png 3x`}
        width={assetConfig.width}
        height={assetConfig.height}
        alt="角色立绘"
        onError={() => {
          setLoadFailed(true);
          console.error(
            `[FE-ANI-002] CharacterAssetError: Dashboard 静态立绘加载失败 (path: ${basePath}-*.png)`,
          );
        }}
      />
    </div>
  );
}

// =============================================================================
// 子组件：Chat 角色头像
// =============================================================================

interface ChatAvatarProps {
  position: CharacterPosition;
  zIndex: number;
  staticFallback?: string | null;
  page: CharacterPage;
}

/** Chat 角色头像（圆形，96px）+ 输入框旁小立绘 */
function ChatAvatar(props: ChatAvatarProps): ReactElement {
  const { position, zIndex, staticFallback, page } = props;
  const [loadFailed, setLoadFailed] = useState(false);
  const assetConfig = DEFAULT_ASSET_PATHS[page];
  const basePath = staticFallback ?? assetConfig.base;

  const style: CSSProperties = {
    position: 'absolute',
    [position === 'avatar' ? 'left' : 'right']: '8px',
    bottom: '8px',
    width: assetConfig.width,
    height: assetConfig.height,
    borderRadius: '50%',
    overflow: 'hidden',
    zIndex,
    pointerEvents: 'none',
  };

  if (loadFailed) {
    return <FallbackPlaceholder style={style} altColor />;
  }

  return (
    <div data-character-host="chat" style={style}>
      <img
        src={`${basePath}-1x.png`}
        srcSet={`${basePath}-1x.png 1x, ${basePath}-2x.png 2x, ${basePath}-3x.png 3x`}
        width={assetConfig.width}
        height={assetConfig.height}
        alt="角色头像"
        onError={() => {
          setLoadFailed(true);
          console.error(
            `[FE-ANI-002] CharacterAssetError: Chat 角色头像加载失败 (path: ${basePath}-*.png)`,
          );
        }}
      />
    </div>
  );
}

// =============================================================================
// 子组件：AudioWorkstation 顶部装饰条带
// =============================================================================

interface TopbarDecorationProps {
  position: CharacterPosition;
  zIndex: number;
  staticFallback?: string | null;
  page: CharacterPage;
}

/** AudioWorkstation 顶部装饰条带（半透明角色剪影） */
function TopbarDecoration(props: TopbarDecorationProps): ReactElement {
  const { position, zIndex, staticFallback, page } = props;
  const [loadFailed, setLoadFailed] = useState(false);
  const assetConfig = DEFAULT_ASSET_PATHS[page];
  const basePath = staticFallback ?? assetConfig.base;
  void position;

  const style: CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: assetConfig.height,
    zIndex,
    pointerEvents: 'none',
    opacity: 0.3,
    overflow: 'hidden',
  };

  if (loadFailed) {
    return <FallbackPlaceholder style={style} />;
  }

  return (
    <div data-character-host="audiowstation" style={style}>
      <img
        src={`${basePath}-1x.png`}
        srcSet={`${basePath}-1x.png 1x, ${basePath}-2x.png 2x, ${basePath}-3x.png 3x`}
        width={assetConfig.width}
        height={assetConfig.height}
        alt="角色剪影装饰"
        onError={() => {
          setLoadFailed(true);
          console.error(
            `[FE-ANI-002] CharacterAssetError: AudioWorkstation 顶部装饰条带加载失败 (path: ${basePath}-*.png)`,
          );
        }}
      />
    </div>
  );
}

// =============================================================================
// 子组件：Live/Pet 交互占位容器
// =============================================================================

interface InteractiveSlotProps {
  position: CharacterPosition;
  zIndex: number;
  page: CharacterPage;
  label: string;
}

/**
 * Live/Pet 页面交互占位容器。
 *
 * 不直接 import Live2D/PetAvatar（跨模块导入约束），
 * 仅提供 z-index=5 的占位容器，由调用方（模块7/8）填充实际组件。
 */
function InteractiveSlot(props: InteractiveSlotProps): ReactElement {
  const { position, zIndex, page, label } = props;
  const assetConfig = DEFAULT_ASSET_PATHS[page];

  const style: CSSProperties = {
    position: 'absolute',
    [position === 'full-interactive' ? 'right' : 'left']: 0,
    bottom: 0,
    width: assetConfig.width,
    height: assetConfig.height,
    zIndex,
    pointerEvents: 'auto',
  };

  return (
    <div
      data-character-host={page}
      data-interactive-slot={label.toLowerCase()}
      style={style}
    >
      {/* 占位容器：由调用方（模块7/8）填充 Live2D / PetAvatar 组件 */}
    </div>
  );
}

// =============================================================================
// 降级占位组件（纯色占位，闭合判据第13项）
// =============================================================================

interface FallbackPlaceholderProps {
  style: CSSProperties;
  altColor?: boolean;
}

/**
 * 角色立绘不可用时的降级纯色占位。
 *
 * 闭合判据第13项: 使用梦境紫或星海青作为占位底色。
 * 控制台错误码已在 onError 中输出（FE-ANI-002）。
 */
function FallbackPlaceholder(props: FallbackPlaceholderProps): ReactElement {
  const { style, altColor = false } = props;
  const bgColor = altColor ? FALLBACK_COLOR_ALT : FALLBACK_COLOR;

  return (
    <div
      data-character-host="fallback"
      data-error-code={ANI_ERROR_CODES.CHARACTER_ASSET_LOAD_FAILED}
      style={{
        ...style,
        backgroundColor: bgColor,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: style.borderRadius ?? 0,
      }}
    >
      <span style={{ color: ANIME_PALETTE.moonlightWhite, fontSize: '10px', opacity: 0.6 }}>
        占位
      </span>
    </div>
  );
}

// =============================================================================
// 资产加载错误辅助函数（供外部调用方使用）
// =============================================================================

/**
 * 创建 CharacterAssetError 异常（供调用方在 ModelLoader.loadAsync 失败时使用）。
 *
 * 对应 I4 §CharacterAssetError。
 * 错误码: FE-ANI-002。
 *
 * @param reason 失败原因
 * @returns CharacterAssetError 实例
 */
export function createCharacterAssetError(reason: string): CharacterAssetError {
  return new CharacterAssetError(
    `CharacterHost: 角色资产加载失败 — ${reason}（errorCode=FE-ANI-002）`,
  );
}
