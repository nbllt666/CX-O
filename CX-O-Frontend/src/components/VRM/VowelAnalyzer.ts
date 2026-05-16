export interface VowelWeights {
  a: number;
  i: number;
  u: number;
  e: number;
  o: number;
}

export class VowelAnalyzer {
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private source: MediaElementAudioSourceNode | null = null;
  private animationFrame: number | null = null;
  private dataArray: Uint8Array | null = null;
  private onVowelDetected: ((weights: VowelWeights) => void) | null = null;

  start(audioElement: HTMLAudioElement, onVowel: (weights: VowelWeights) => void): void {
    this.stop();
    this.onVowelDetected = onVowel;

    try {
      this.audioContext = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.smoothingTimeConstant = 0.6;

      this.source = this.audioContext.createMediaElementSource(audioElement);
      this.source.connect(this.analyser);
      this.analyser.connect(this.audioContext.destination);

      this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);

      this.analyze();
    } catch (error) {
      console.error('Failed to start vowel analyzer:', error);
    }
  }

  stop(): void {
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

    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    this.onVowelDetected = null;
  }

  private analyze = (): void => {
    if (!this.analyser || !this.dataArray || !this.onVowelDetected) {
      return;
    }

    this.analyser.getByteFrequencyData(this.dataArray as Uint8Array<ArrayBuffer>);

    const weights = this.detectVowels(this.dataArray);
    this.onVowelDetected(weights);

    this.animationFrame = requestAnimationFrame(this.analyze);
  };

  private detectVowels(data: Uint8Array): VowelWeights {
    const sampleRate = this.audioContext?.sampleRate || 44100;
    const binSize = sampleRate / 2 / data.length;

    // Formant frequency ranges (approximate)
    // A: F1 ~700-800Hz, F2 ~1200-1300Hz
    // I: F1 ~300-400Hz, F2 ~2000-2500Hz
    // U: F1 ~300-400Hz, F2 ~600-800Hz
    // E: F1 ~400-600Hz, F2 ~1800-2200Hz
    // O: F1 ~400-600Hz, F2 ~800-1000Hz

    const getBandEnergy = (minFreq: number, maxFreq: number): number => {
      const minIdx = Math.floor(minFreq / binSize);
      const maxIdx = Math.ceil(maxFreq / binSize);
      let sum = 0;
      let count = 0;
      for (let i = Math.max(0, minIdx); i <= Math.min(data.length - 1, maxIdx); i++) {
        sum += data[i];
        count++;
      }
      return count > 0 ? sum / count / 255 : 0;
    };

    const f1Low = getBandEnergy(250, 450);
    const f1Mid = getBandEnergy(450, 700);
    const f1High = getBandEnergy(700, 900);
    const f2Low = getBandEnergy(600, 1000);
    const f2Mid = getBandEnergy(1000, 1500);
    const f2High = getBandEnergy(1500, 2500);

    // Simple vowel detection based on formant patterns
    const volume = (f1Low + f1Mid + f1High + f2Low + f2Mid + f2High) / 6;
    if (volume < 0.05) {
      return { a: 0, i: 0, u: 0, e: 0, o: 0 };
    }

    // Calculate vowel probabilities
    const a = f1High * f2Mid * 2.5;
    const i = f1Low * f2High * 2.5;
    const u = f1Low * f2Low * 2.5;
    const e = f1Mid * f2High * 2.0;
    const o = f1Mid * f2Low * 2.0;

    // Normalize
    const max = Math.max(a, i, u, e, o, 0.001);
    const scale = Math.min(1, volume * 3) / max;

    return {
      a: Math.min(1, a * scale),
      i: Math.min(1, i * scale),
      u: Math.min(1, u * scale),
      e: Math.min(1, e * scale),
      o: Math.min(1, o * scale),
    };
  }
}
