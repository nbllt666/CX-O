/**
 * PetContextMenu — 桌宠快捷菜单。
 *
 * 液态玻璃风格单侧椭圆气泡菜单：
 * - 开关项（checked）以主色高亮
 * - 点击窗口任意处 / Escape / 窗口失焦自动关闭
 * - 位置自动收拢到视口内（边缘不溢出）
 *
 * 菜单容器经 menuRef 注册进鼠标穿透命中区，
 * 否则穿透状态下菜单浮在空区上无法交互。
 */
import { useEffect } from 'react';
import type { ReactNode, RefObject } from 'react';
import { CAPTURE_BASE_WIDTH, CAPTURE_BASE_HEIGHT } from '../../store/obsStore';

export interface PetContextMenuItem {
  key: string;
  label: string;
  icon?: ReactNode;
  /** 开关项勾选态（传入即视为开关项） */
  checked?: boolean;
  onSelect: () => void;
  slider?: {
    value: number;
    min: number;
    max: number;
    step: number;
    onChange: (value: number) => void;
  };
}

interface PetContextMenuProps {
  position: { x: number; y: number } | null;
  items: PetContextMenuItem[];
  onClose: () => void;
  /** 注册到 useMousePassthrough 的附加交互区 */
  menuRef: RefObject<HTMLDivElement>;
}

// 按钮半宽（48px 圆形按钮的一半）
const BTN_HALF = 24;
const VIEWPORT_GAP = 8;
// 椭圆半径与菜单容器之间的留白
const RADIUS_MARGIN = 8;
// 弧心垂直偏置（px）：负数上移，让单侧椭圆更贴近头像上半身，避免菜单整体偏低
const ARC_BIAS_Y = -14;
// 横向半径收拢系数：<1 时 RX 相对 RY 变小，中间按钮往内收，弧线更平缓（曲率更小）
// 注意：压扁 RY 反而会让上下按钮靠拢、横向凸出不变，显得更"鼓"更弯，所以改压 RX。
// 收拢过多会让相邻按钮横向间距 < 按钮宽（48px）导致拥挤，故取 0.92 兼顾平缓与分散。
const RX_FLATTEN = 0.92;

export function PetContextMenu({ position, items, onClose, menuRef }: PetContextMenuProps) {
  // 点击他处 / Escape / 窗口失焦（穿透点击落到桌面）时关闭
  useEffect(() => {
    if (!position) return;
    let ignoreOpeningClick = true;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    const handleWindowClick = () => {
      if (ignoreOpeningClick) {
        ignoreOpeningClick = false;
        return;
      }
      onClose();
    };
    const timer = window.setTimeout(() => {
      ignoreOpeningClick = false;
      window.addEventListener('click', handleWindowClick);
    }, 0);
    window.addEventListener('blur', onClose);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('click', handleWindowClick);
      window.removeEventListener('blur', onClose);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [position, onClose]);

  if (!position) return null;

  // 按真实窗口尺寸自适应，避免在小桌宠窗口（400×500）中菜单比窗口还大。
  // 菜单随窗口相对基准（400×500）同比例放大：模型放大→窗口联动放大→菜单同步放大，
  // 按钮间距随之拉大，不再拥挤（与 PetPage 的「窗口随 scale 缩放」逻辑一致）。
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const menuScale = Math.max(
    Math.min(vw / CAPTURE_BASE_WIDTH, vh / CAPTURE_BASE_HEIGHT),
    1,
  );
  const MENU_WIDTH = Math.min(vw - VIEWPORT_GAP * 2, 400 * menuScale);
  const MENU_HEIGHT = Math.min(vh - VIEWPORT_GAP * 2, 420 * menuScale);
  const CX = MENU_WIDTH / 2;
  const CY = MENU_HEIGHT / 2;
  const RX = Math.max((CX - BTN_HALF - RADIUS_MARGIN) * RX_FLATTEN, 40);
  const RY = Math.max(CY - BTN_HALF - RADIUS_MARGIN, 40);

  const left = Math.max(
    VIEWPORT_GAP,
    Math.min(position.x - CX, vw - MENU_WIDTH - VIEWPORT_GAP),
  );
  const top = Math.max(
    VIEWPORT_GAP,
    Math.min(position.y - CY, vh - MENU_HEIGHT - VIEWPORT_GAP),
  );

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label="桌宠快捷选项"
      className="fixed z-50"
      style={{ left, top, width: MENU_WIDTH, height: MENU_HEIGHT }}
      onContextMenu={(e) => e.preventDefault()}
      onClick={(e) => e.stopPropagation()}
    >
      {items.map((item, index) => {
        const progress = index / Math.max(items.length - 1, 1);
        const angle = -Math.PI / 2 + progress * Math.PI;
        const x = CX + Math.cos(angle) * RX;
        const y = CY + ARC_BIAS_Y + Math.sin(angle) * RY;
        return (
          <button
            key={item.key}
            type="button"
            role="menuitem"
            aria-label={item.label}
            aria-pressed={item.checked}
            onClick={item.onSelect}
            className={`group pet-menu-bubble absolute flex h-12 w-12 items-center justify-center rounded-full border text-foreground shadow-lg backdrop-blur-xl ${
              item.slider
                ? ''
                : 'transition-transform duration-fast hover:scale-110 active:scale-95'
            } ${
              item.checked
                ? 'border-primary/70 bg-primary/80 text-primary-foreground'
                : 'border-white/30 bg-background/80 hover:border-primary/50 hover:bg-primary/20'
            }`}
            style={{
              left: x - BTN_HALF,
              top: y - BTN_HALF,
              animationDelay: `${index * 25}ms`,
            }}
          >
            {item.icon}
            <span className="pet-menu-label pointer-events-none absolute left-[54px] top-1/2 -translate-y-1/2 whitespace-nowrap rounded-full px-2 py-1 text-[10px] leading-none text-foreground opacity-0 transition-opacity duration-fast group-hover:opacity-100">
              {item.label}
            </span>
            {item.slider && (
              <span
                className="pet-menu-slider glass-panel absolute right-[58px] top-1/2 flex -translate-y-1/2 items-center gap-2 rounded-full px-3 py-2"
                onPointerDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
              >
                <input
                  aria-label={item.label}
                  type="range"
                  min={item.slider.min}
                  max={item.slider.max}
                  step={item.slider.step}
                  value={item.slider.value}
                  onChange={(event) => item.slider?.onChange(Number(event.target.value))}
                />
                <span className="w-9 text-right text-[10px] tabular-nums">
                  {Math.round(item.slider.value * 100)}%
                </span>
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
