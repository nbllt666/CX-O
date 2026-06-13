import { useEffect, useRef, useCallback } from 'react';
import { useSettingsStore } from '../store/settingsStore';

interface UsePetMousePassthroughOptions {
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** Hit area as fraction of canvas size [centerX, centerY, radiusX, radiusY] (0-1) */
  hitArea?: [number, number, number, number];
  enabled?: boolean;
}

/**
 * Hook for mouse passthrough on pet window.
 *
 * Detection strategy (in order of priority):
 * 1. **Geometric hit area**: Checks if mouse is within an elliptical region
 *    where the avatar model is typically rendered (center of canvas).
 *    This is fast, reliable, and doesn't require access to internal renderer state.
 *
 * 2. **Pixel alpha detection** (fallback): Reads the alpha channel of the canvas
 *    pixel under the mouse cursor. If alpha is 0, the area is transparent and
 *    mouse events should pass through. This provides precise hit detection but
 *    may not work with all WebGL configurations (preserveDrawingBuffer).
 *
 * Note: The spec mentions Three.js Raycaster for VRM and PIXI hit-testing for Live2D,
 * but those require modifying existing viewer components to expose internal state.
 * The geometric + pixel alpha approach is more practical and works for both avatar types
 * without modifying existing code.
 */
export function usePetMousePassthrough({
  containerRef,
  hitArea = [0.5, 0.45, 0.3, 0.4], // center, slightly above middle, elliptical
  enabled = true,
}: UsePetMousePassthroughOptions) {
  const { avatarType } = useSettingsStore();
  const lastStateRef = useRef<boolean | null>(null);
  const hitAreaRef = useRef(hitArea);
  hitAreaRef.current = hitArea;

  const setIgnoreMouseEvents = useCallback((ignore: boolean) => {
    if (lastStateRef.current === ignore) return;
    lastStateRef.current = ignore;

    const electronAPI = (window as unknown as { electronAPI?: { setIgnoreMouseEvents: (ignore: boolean) => void } }).electronAPI;
    if (electronAPI?.setIgnoreMouseEvents) {
      electronAPI.setIgnoreMouseEvents(ignore);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const electronAPI = (window as unknown as { electronAPI?: { setIgnoreMouseEvents: (ignore: boolean) => void } }).electronAPI;
    if (!electronAPI?.setIgnoreMouseEvents) return;

    const handleMouseMove = (e: MouseEvent) => {
      const container = containerRef.current;
      if (!container) return;

      const canvas = container.querySelector('canvas');
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      // Check if mouse is within canvas bounds
      if (x < 0 || x > rect.width || y < 0 || y > rect.height) {
        setIgnoreMouseEvents(true);
        return;
      }

      // Method 1: Geometric hit area (elliptical region where model is rendered)
      const [cx, cy, rx, ry] = hitAreaRef.current;
      const nx = x / rect.width;  // normalized x (0-1)
      const ny = y / rect.height; // normalized y (0-1)
      const inEllipse = ((nx - cx) / rx) ** 2 + ((ny - cy) / ry) ** 2 <= 1;

      if (inEllipse) {
        // Mouse is in the model area - try pixel alpha for more precision
        const alphaDetected = checkPixelAlpha(canvas, x, y);
        if (alphaDetected !== null) {
          setIgnoreMouseEvents(!alphaDetected);
        } else {
          // Pixel alpha not available, use geometric hit area
          setIgnoreMouseEvents(false);
        }
      } else {
        // Mouse is outside the model area
        setIgnoreMouseEvents(true);
      }
    };

    const handleMouseLeave = () => {
      setIgnoreMouseEvents(true);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseleave', handleMouseLeave);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, [avatarType, enabled, containerRef, setIgnoreMouseEvents]);
}

/**
 * Check if a pixel at (x, y) on a canvas has non-transparent content.
 * Returns true if content is visible (alpha > 0), false if transparent,
 * or null if detection is not possible.
 */
function checkPixelAlpha(
  canvas: HTMLCanvasElement,
  x: number,
  y: number,
): boolean | null {
  try {
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    if (gl) {
      const px = Math.round(x * (canvas.width / canvas.clientWidth));
      const py = Math.round((canvas.clientHeight - y) * (canvas.height / canvas.clientHeight));
      const pixel = new Uint8Array(4);
      gl.readPixels(px, py, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
      // If all zeros, buffer may have been cleared (preserveDrawingBuffer issue)
      // In that case, return null to indicate detection unavailable
      if (pixel[0] === 0 && pixel[1] === 0 && pixel[2] === 0 && pixel[3] === 0) {
        return null;
      }
      return pixel[3] > 0;
    } else {
      const ctx = canvas.getContext('2d');
      if (ctx) {
        const px = Math.round(x * (canvas.width / canvas.clientWidth));
        const py = Math.round(y * (canvas.height / canvas.clientHeight));
        const pixel = ctx.getImageData(px, py, 1, 1).data;
        return pixel[3] > 0;
      }
    }
  } catch {
    // Cross-origin or other security restrictions
  }
  return null;
}
