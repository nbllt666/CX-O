import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// pixi-live2d-display/cubism4 在模块求值时强制校验 window.Live2DCubismCore
// （浏览器/Electron 由 index.html 先加载本地 cubism core 脚本；jsdom 无此全局）。
// 测试从不实例化 Live2D 运行时（avatarType 默认 none），全局打桩截断该 import 链，
// 使任何经路由静态 import 到 PetPage→PetAvatar→live2dEngine 的测试文件免于整链加载。
vi.mock('pixi-live2d-display/cubism4', () => ({
  Live2DModel: class {
    static from(): never {
      throw new Error('Live2DModel.from 不应在单测环境被调用');
    }
  },
}));

// jsdom 未实现 Element.prototype.scrollIntoView；PetChat 等组件在 effect 中调用会抛
// `scrollIntoView is not a function`。?. 可选链只防 null ref，防不了方法缺失，
// 在测试环境统一打桩（浏览器/Electron 中为原生实现，不影响生产行为）。
if (typeof window !== 'undefined' && !window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = () => {};
}
