/**
 * 头像源页（SubTask 8.2，管理窗内路由 avatar-source + 顶层 OBS 路由 /source/avatar-source）
 *
 * 复用 Task 3 头像系统：直接渲染 PetAvatar（自读 settingsStore 选择 Live2D/VRM 独立驱动实例）。
 * 本页为自包含 OBS 浏览器源：透明背景、1920×1080 画布、无管理布局依赖。
 * document.body 置透明，OBS 浏览器源勾选透明背景即可抠像。
 */
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { PetAvatar } from '@/components/pet/PetAvatar';

export default function AvatarSourcePage() {
  const { t } = useTranslation();

  // OBS 透明背景：页面与根元素透明，配合浏览器源透明背景使用
  useEffect(() => {
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = '';
      document.documentElement.style.background = '';
    };
  }, []);

  return (
    <div
      className="relative flex items-center justify-center"
      style={{ backgroundColor: 'transparent', width: 1920, height: 1080, overflow: 'hidden' }}
    >
      <PetAvatar />

      {/* 底部来源提示（可被 OBS 覆盖，仅作定位参考） */}
      <div className="pointer-events-none absolute bottom-3 right-4 rounded-md bg-black/30 px-2 py-0.5 text-[10px] text-white/50">
        {t('management.avatarSource.obsHint')} · 1920×1080
      </div>
    </div>
  );
}
