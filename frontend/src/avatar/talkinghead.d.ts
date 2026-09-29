// Типы только для того, что вызываем из TalkingHead 1.7 (у пакета своих .d.ts нет)
declare module "@met4citizen/talkinghead" {
  export type SpeakAudio = { audio: AudioBuffer; words: string[]; wtimes: number[]; wdurations: number[] };
  export class TalkingHead {
    constructor(node: HTMLElement, opt?: Record<string, unknown>);
    audioCtx: AudioContext;
    lipsync: Record<string, unknown>;
    animMoods: Record<string, Record<string, unknown>>;
    renderer: { toneMapping: number };
    showAvatar(avatar: Record<string, unknown>, onprogress?: (ev: ProgressEvent) => void): Promise<void>;
    setMood(mood: string): void;
    speakAudio(r: SpeakAudio, opt?: Record<string, unknown>, onsubtitles?: ((node: unknown) => void) | null): void;
    stopSpeaking(): void;
    dispose(): void;
  }
}
