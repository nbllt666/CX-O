import { Button, Card, CardBody } from '../../../components/ui';
import { SaveStatus } from '../types';
import type { AvatarType } from '../../../store/settingsStore';

export interface Live2DCardProps {
  showAvatarManager: 'live2d' | 'vrm' | null;
  onShowAvatarManagerChange: (show: 'live2d' | 'vrm' | null) => void;
  speedMax: number;
  onSpeedMaxChange: (speed: number) => void;
  avatarType: AvatarType;
  onAvatarTypeChange: (type: AvatarType) => void;
  limits: any;
  onSave: () => void;
  saveStatus: SaveStatus;
}

export function Live2DCard(props: Live2DCardProps) {
  const {
    onShowAvatarManagerChange,
    avatarType,
    onAvatarTypeChange,
    onSave,
    saveStatus,
  } = props;

  return (
    <div className="space-y-6">
      {/* 虚拟形象类型选择 */}
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">虚拟形象类型</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            选择在聊天页面显示的虚拟形象类型
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => onAvatarTypeChange('none')}
              className={`flex-1 p-3 rounded-[var(--radius-md)] border transition-colors ${
                avatarType === 'none'
                  ? 'border-[var(--color-accent)] bg-[var(--color-accent-light)]'
                  : 'border-[var(--color-border)] hover:border-[var(--color-accent)]'
              }`}
            >
              <div className="text-center">
                <svg className="w-6 h-6 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                </svg>
                <span className="text-sm font-medium">无</span>
              </div>
            </button>
            <button
              onClick={() => onAvatarTypeChange('live2d')}
              className={`flex-1 p-3 rounded-[var(--radius-md)] border transition-colors ${
                avatarType === 'live2d'
                  ? 'border-[var(--color-accent)] bg-[var(--color-accent-light)]'
                  : 'border-[var(--color-border)] hover:border-[var(--color-accent)]'
              }`}
            >
              <div className="text-center">
                <svg className="w-6 h-6 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="text-sm font-medium">Live2D</span>
              </div>
            </button>
            <button
              onClick={() => onAvatarTypeChange('vrm')}
              className={`flex-1 p-3 rounded-[var(--radius-md)] border transition-colors ${
                avatarType === 'vrm'
                  ? 'border-[var(--color-accent)] bg-[var(--color-accent-light)]'
                  : 'border-[var(--color-border)] hover:border-[var(--color-accent)]'
              }`}
            >
              <div className="text-center">
                <svg className="w-6 h-6 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
                <span className="text-sm font-medium">VRM 3D</span>
              </div>
            </button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">Live2D 虚拟形象</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            在聊天页面显示 Live2D 虚拟形象，支持口型同步和表情动画
          </p>
          <button
            onClick={() => onShowAvatarManagerChange('live2d')}
            className="w-full px-4 py-3 text-sm bg-[var(--color-accent)] text-white rounded-[var(--radius-md)] hover:opacity-90 transition-opacity flex items-center justify-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            打开 Live2D 配置面板
          </button>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">VRM 3D 虚拟形象</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            在聊天页面显示 VRM 3D 虚拟形象，支持口型同步、视线追踪和渲染调节
          </p>
          <button
            onClick={() => onShowAvatarManagerChange('vrm')}
            className="w-full px-4 py-3 text-sm bg-[var(--color-accent)] text-white rounded-[var(--radius-md)] hover:opacity-90 transition-opacity flex items-center justify-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            打开 VRM 配置面板
          </button>
        </CardBody>
      </Card>

      <div className="flex justify-end mt-6">
        <Button onClick={onSave} loading={saveStatus === 'saving'}>
          {saveStatus === 'saved' ? '已保存' : '保存配置'}
        </Button>
      </div>
    </div>
  );
}
