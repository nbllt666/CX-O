import React from 'react';
import { cn } from '../../lib/utils';

export interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  position?: 'left' | 'right';
  width?: string;
}

export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  children,
  position = 'right',
  width = '400px',
}) => {
  if (!isOpen) return null;

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40 transition-opacity" onClick={onClose} />
      <div
        className={cn(
          'fixed top-0 bottom-0 z-50 bg-[var(--color-bg-primary)] shadow-xl transition-transform duration-300',
          position === 'right' ? 'right-0' : 'left-0'
        )}
        style={{ width }}
      >
        <div className="flex items-center justify-between p-4 border-b border-[var(--color-border)]">
          {title && (
            <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">{title}</h2>
          )}
          <button
            onClick={onClose}
            className="p-2 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-md)] transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>
        <div className="p-4 overflow-y-auto h-[calc(100%-60px)]">{children}</div>
      </div>
    </>
  );
};
