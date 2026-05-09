export class AudioAnalyzer {
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private dataArray: Uint8Array | null = null;
  private source: MediaElementAudioSourceNode | null = null;
  private currentAudioElement: HTMLAudioElement | null = null;
  private animationFrame: number | null = null;
  private onVolumeChange: ((volume: number) => void) | null = null;

  connect(audioElement: HTMLAudioElement, onVolume: (volume: number) => void): void {
    if (this.currentAudioElement === audioElement && this.analyser) {
      this.onVolumeChange = onVolume;
      return;
    }

    this.disconnect();
    this.currentAudioElement = audioElement;
    this.onVolumeChange = onVolume;

    try {
      this.audioContext = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.8;

      const bufferLength = this.analyser.frequencyBinCount;
      this.dataArray = new Uint8Array(bufferLength);

      this.source = this.audioContext.createMediaElementSource(audioElement);
      this.source.connect(this.analyser);
      this.analyser.connect(this.audioContext.destination);

      this.startAnalysis();
    } catch (error) {
      console.error('AudioAnalyzer: Failed to connect audio element:', error);
    }
  }

  private startAnalysis(): void {
    const analyze = (): void => {
      if (!this.analyser || !this.dataArray || !this.onVolumeChange) {
        return;
      }

      this.analyser.getByteFrequencyData(this.dataArray as Uint8Array<ArrayBuffer>);

      const sum = this.dataArray.reduce((acc, val) => acc + val, 0);
      const average = sum / this.dataArray.length;
      const normalizedVolume = Math.min(average / 128, 1);

      this.onVolumeChange(normalizedVolume);

      this.animationFrame = requestAnimationFrame(analyze);
    };

    analyze();
  }

  disconnect(): void {
    if (this.animationFrame !== null) {
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }

    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }

    if (this.analyser) {
      this.analyser.disconnect();
      this.analyser = null;
    }

    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close();
      this.audioContext = null;
    }

    this.dataArray = null;
    this.currentAudioElement = null;
    this.onVolumeChange = null;
  }

  getVolume(): number {
    if (!this.analyser || !this.dataArray) {
      return 0;
    }

    this.analyser.getByteFrequencyData(this.dataArray as Uint8Array<ArrayBuffer>);
    const sum = this.dataArray.reduce((acc, val) => acc + val, 0);
    return Math.min(sum / this.dataArray.length / 128, 1);
  }
}

export const audioAnalyzer = new AudioAnalyzer();
