/**
 * 真实本机驱动（仅在主进程使用，禁止在单测中导入——会触发 electron 依赖）。
 *
 * - 屏幕采集：Electron desktopCapturer（与 main.ts 屏幕共享同一能力）。
 * - 鼠标/键盘：Windows 下经 PowerShell user32 P/Invoke（无机器人库依赖、免原生编译）
 *   实现全局输入；非 Windows 平台抛错（当前阶段仅支持 Windows 桌面）。
 *
 * 单测一律注入 mock 替身（见 screen.ts / keyboard.ts），本文件不在测试路径中。
 */
import { desktopCapturer } from 'electron';
import { execFile } from 'node:child_process';
import type { CaptureResult, ScreenDriver } from './screen';
import type { KeyboardDriver } from './keyboard';

function isWindows(): boolean {
  return process.platform === 'win32';
}

function runPowershell(script: string): Promise<void> {
  return new Promise((resolve, reject) => {
    execFile(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', script],
      { windowsHide: true, timeout: 15_000 },
      (err) => {
        if (err) reject(new Error(`native driver failed: ${err.message}`));
        else resolve();
      },
    );
  });
}

/** Windows 通用 user32 P/Invoke 头，供鼠标/键盘脚本复用 */
const USER32_TYPEDEF = `
Add-Type @"
using System.Runtime.InteropServices;
public static class CCUser32 {
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,uint e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk,byte scan,uint flags,uint extra);
  [DllImport("user32.dll")] public static extern short VkKeyScan(char c);
}
"@
`;

export class NativeScreenDriver implements ScreenDriver {
  async capture(): Promise<CaptureResult> {
    const sources = await desktopCapturer.getSources({
      types: ['screen'],
      thumbnailSize: { width: 0, height: 0 },
    });
    if (!sources.length) throw new Error('未找到屏幕源');
    const source = sources[0];
    const thumb = source.thumbnail;
    if (thumb.isEmpty()) throw new Error('屏幕缩略图为空');
    const size = thumb.getSize();
    return {
      mimeType: 'image/png',
      dataUrl: thumb.toDataURL(),
      width: size.width,
      height: size.height,
    };
  }

  async move(x: number, y: number): Promise<void> {
    if (!isWindows()) throw new Error('move 仅支持 Windows');
    const script = `Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${Math.round(x)},${Math.round(y)})`;
    await runPowershell(script);
  }

  async click(x: number, y: number, button: 'left' | 'right' | 'middle' = 'left'): Promise<void> {
    if (!isWindows()) throw new Error('click 仅支持 Windows');
    // 先移动指针到目标点，再按下/抬起（mouse_event 的 down/up 标志位）
    const downUp =
      button === 'right' ? '8,16' : button === 'middle' ? '32,64' : '2,4';
    const script = `${USER32_TYPEDEF}
Add-Type -AssemblyName System.Windows.Forms;
[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${Math.round(x)},${Math.round(y)});
Start-Sleep -Milliseconds 20;
$parts = @(${downUp} -split ',');
[CCUser32]::mouse_event([uint32]$parts[0],0,0,0,0);
[CCUser32]::mouse_event([uint32]$parts[1],0,0,0,0)`;
    await runPowershell(script);
  }

  async scroll(delta: number, x?: number, y?: number): Promise<void> {
    if (!isWindows()) throw new Error('scroll 仅支持 Windows');
    const moveLine = x !== undefined && y !== undefined
      ? `[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(${Math.round(x)},${Math.round(y)});`
      : '';
    const wheel = Math.round(delta);
    const script = `${USER32_TYPEDEF}
Add-Type -AssemblyName System.Windows.Forms;
${moveLine}
[CCUser32]::mouse_event(0x0800,0,0,[uint32]${wheel},0)`;
    await runPowershell(script);
  }
}

/** 简单 VK 码映射（常用键 + 字母/数字）；未映射键回退为 null */
function vkCode(key: string): number | null {
  if (/^[a-zA-Z]$/.test(key)) return key.toUpperCase().charCodeAt(0);
  if (/^[0-9]$/.test(key)) return key.charCodeAt(0);
  const map: Record<string, number> = {
    enter: 13, return: 13, tab: 9, space: 32, backspace: 8, escape: 27,
    up: 38, down: 40, left: 37, right: 39, home: 36, end: 35,
    pageup: 33, pagedown: 34, delete: 46, insert: 45,
    f1: 112, f2: 113, f3: 114, f4: 115, f5: 116, f6: 117,
    f7: 118, f8: 119, f9: 120, f10: 121, f11: 122, f12: 123,
  };
  return map[key.toLowerCase()] ?? null;
}

export class NativeKeyboardDriver implements KeyboardDriver {
  private async sendVk(vk: number): Promise<void> {
    const script = `${USER32_TYPEDEF}
[CCUser32]::keybd_event([byte]${vk},0,0,0);
[CCUser32]::keybd_event([byte]${vk},0,2,0)`;
    await runPowershell(script);
  }

  async type(text: string): Promise<void> {
    if (!isWindows()) throw new Error('type 仅支持 Windows');
    if (!text) return;
    const script = `Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('${text.replace(/'/g, "''")}')`;
    await runPowershell(script);
  }

  async press(code: string): Promise<void> {
    if (!isWindows()) throw new Error('press 仅支持 Windows');
    const vk = vkCode(code);
    if (vk === null) throw new Error(`不支持的按键: ${code}`);
    await this.sendVk(vk);
  }

  async hotkey(modifiers: string[], key: string): Promise<void> {
    if (!isWindows()) throw new Error('hotkey 仅支持 Windows');
    const vk = vkCode(key);
    if (vk === null) throw new Error(`不支持的按键: ${key}`);
    const modVk: Record<string, number> = { ctrl: 17, shift: 16, alt: 18, meta: 91 };
    const mods = modifiers.map((m) => modVk[m]).filter((v): v is number => v !== undefined);
    const down = [...mods, vk];
    const up = [...down].reverse();
    const lines = [
      USER32_TYPEDEF,
      ...down.map((v) => `[CCUser32]::keybd_event([byte]${v},0,0,0);`),
      ...up.map((v) => `[CCUser32]::keybd_event([byte]${v},0,2,0);`),
    ].join('\n');
    await runPowershell(lines);
  }
}
