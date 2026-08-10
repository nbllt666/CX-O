import { createRef } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PetContextMenu } from './PetContextMenu';

afterEach(cleanup);

describe('PetContextMenu', () => {
  it('以圆形气泡渲染所有选项并标识开关状态', () => {
    const menuRef = createRef<HTMLDivElement>();
    render(
      <PetContextMenu
        position={{ x: 180, y: 180 }}
        items={[
          { key: 'settings', label: '设置', onSelect: vi.fn() },
          { key: 'pin', label: '置顶', checked: true, onSelect: vi.fn() },
        ]}
        onClose={vi.fn()}
        menuRef={menuRef}
      />,
    );

    expect(screen.getByRole('menu', { name: '桌宠快捷选项' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '设置' })).toHaveClass('pet-menu-bubble');
    expect(screen.getByRole('menuitem', { name: '置顶' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('点击选项调用对应动作', () => {
    const onSelect = vi.fn();
    render(
      <PetContextMenu
        position={{ x: 180, y: 180 }}
        items={[{ key: 'settings', label: '设置', onSelect }]}
        onClose={vi.fn()}
        menuRef={createRef<HTMLDivElement>()}
      />,
    );

    fireEvent.click(screen.getByRole('menuitem', { name: '设置' }));
    expect(onSelect).toHaveBeenCalledOnce();
  });

  it('按 Escape 关闭菜单', () => {
    const onClose = vi.fn();
    render(
      <PetContextMenu
        position={{ x: 180, y: 180 }}
        items={[{ key: 'settings', label: '设置', onSelect: vi.fn() }]}
        onClose={onClose}
        menuRef={createRef<HTMLDivElement>()}
      />,
    );

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('位置靠近视口边缘时自动收拢', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 400 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 500 });
    render(
      <PetContextMenu
        position={{ x: 0, y: 0 }}
        items={[{ key: 'settings', label: '设置', onSelect: vi.fn() }]}
        onClose={vi.fn()}
        menuRef={createRef<HTMLDivElement>()}
      />,
    );

    const menu = screen.getByRole('menu', { name: '桌宠快捷选项' });
    expect(menu).toHaveStyle({ left: '8px', top: '8px' });
  });

  it('支持在菜单内拖动滑动条并回调缩放值', () => {
    const onChange = vi.fn();
    render(
      <PetContextMenu
        position={{ x: 180, y: 180 }}
        items={[
          {
            key: 'scale',
            label: '头像缩放：100%',
            onSelect: vi.fn(),
            slider: { value: 1, min: 0.6, max: 1.6, step: 0.05, onChange },
          },
        ]}
        onClose={vi.fn()}
        menuRef={createRef<HTMLDivElement>()}
      />,
    );

    const slider = screen.getByRole('slider', { name: '头像缩放：100%' });
    fireEvent.change(slider, { target: { value: '1.4' } });
    expect(onChange).toHaveBeenCalledWith(1.4);
  });
});
