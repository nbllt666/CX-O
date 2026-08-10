/**
 * 弹幕播报队列（纯逻辑，SubTask 4.4）。
 *
 * 策略：FIFO + 容量上限，超限丢弃最旧条目（弹幕时效性强，
 * 播报 3 分钟前的弹幕不如播最新的）；clear 用于开关关闭时立即清空待播。
 */
export interface DanmakuSpeechItem {
  id: string;
  text: string;
}

export const DEFAULT_SPEECH_QUEUE_CAPACITY = 3;

export class DanmakuSpeechQueue {
  private items: DanmakuSpeechItem[] = [];
  private readonly capacity: number;

  constructor(capacity: number = DEFAULT_SPEECH_QUEUE_CAPACITY) {
    this.capacity = Math.max(1, Math.floor(capacity));
  }

  /** 入队；超容量时丢弃最旧条目。返回被丢弃的最旧条目（无则 null） */
  enqueue(item: DanmakuSpeechItem): DanmakuSpeechItem | null {
    this.items.push(item);
    if (this.items.length > this.capacity) {
      return this.items.shift() ?? null;
    }
    return null;
  }

  dequeue(): DanmakuSpeechItem | undefined {
    return this.items.shift();
  }

  clear(): void {
    this.items = [];
  }

  get size(): number {
    return this.items.length;
  }
}
