import { useEffect, useRef, useState } from "react";
import { TalkingHead } from "@met4citizen/talkinghead";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { api, Mood, ScenarioCard, Speech } from "../api";
import { LipsyncRu } from "./lipsync-ru";
import { b64ToArrayBuffer, estimateTimings } from "./speech";

// TalkingHead 1.7 из npm создаёт GLTFLoader без декодера Meshopt; подключаем его, чтобы грузить сжатые модели (наша весит 3 МБ вместо 37)
const parse = GLTFLoader.prototype.parse;
GLTFLoader.prototype.parse = function (this: GLTFLoader, ...args: Parameters<GLTFLoader["parse"]>) {
  this.setMeshoptDecoder(MeshoptDecoder);
  return parse.apply(this, args);
};

export type Say = { id: number; text: string; mood: Mood };
type Props = { url: string; gender: ScenarioCard["voice"]; mood: Mood; say: Say | null; ttsReady: boolean; onFail: (msg: string) => void; onSpeaking?: (on: boolean) => void };

// Собеседник в 3D: TalkingHead + русский липсинк. Озвучка от бэка (Yandex TTS с таймингами слов),
// без неё — беззвучная тишина той же длины и тайминги по длине слов, текст показывается субтитром.
export default function Avatar3D({ url, gender, mood, say, ttsReady, onFail, onSpeaking }: Props) {
  const node = useRef<HTMLDivElement>(null);
  const head = useRef<TalkingHead | null>(null);
  const pending = useRef<Say | null>(null);
  const spoken = useRef<number | null>(null);
  const [ready, setReady] = useState(false);
  const [progress, setProgress] = useState(0);
  const [subtitle, setSubtitle] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    let h: TalkingHead;
    try {
      h = new TalkingHead(node.current!, { lipsyncModules: [], lipsyncLang: "ru", cameraView: "upper", cameraDistance: -1, cameraY: -0.1, cameraRotateEnable: false, avatarMood: mood, modelFPS: 30 });
    } catch (e) { onFail(`3D не запустился: ${(e as Error).message}`); return; }
    h.lipsync.ru = new LipsyncRu();
    head.current = h;
    h.showAvatar({ url, body: gender === "male" ? "M" : "F", avatarMood: mood, lipsyncLang: "ru" }, (ev) => { if (ev.lengthComputable) setProgress(Math.round((100 * ev.loaded) / ev.total)); })
      .then(() => { if (alive) setReady(true); })
      .catch((e) => { if (alive) onFail(`3D-модель не загрузилась: ${e?.message ?? e}`); });
    return () => { alive = false; setReady(false); onSpeaking?.(false); head.current = null; try { h.dispose(); } catch { /* уже остановлен */ } };
  }, [url, gender]);

  useEffect(() => { if (ready) try { head.current?.setMood(mood); } catch { /* неизвестное настроение — оставляем прежнее */ } }, [mood, ready]);

  const speak = async (s: Say) => {
    const h = head.current;
    if (!h || spoken.current === s.id) return;
    spoken.current = s.id;
    setBusy(true); setNote("");
    let speech: Speech | null = null;
    if (ttsReady) {
      try { speech = await api.tts(s.text, s.mood, gender); } catch (e) { setNote(`Озвучка недоступна, собеседник говорит без звука. ${(e as Error).message}`); }
    }
    if (head.current !== h) return;
    try { h.setMood(s.mood); } catch { /* см. выше */ }
    let audio: AudioBuffer;
    let timing = speech?.words.length ? { words: speech.words, wtimes: speech.wtimes, wdurations: speech.wdurations } : estimateTimings(s.text);
    try {
      if (!speech?.audio) throw new Error("no audio");
      audio = await h.audioCtx.decodeAudioData(b64ToArrayBuffer(speech.audio));
    } catch {
      const est = estimateTimings(s.text);
      timing = est;
      audio = h.audioCtx.createBuffer(1, Math.ceil((h.audioCtx.sampleRate * est.total) / 1000), h.audioCtx.sampleRate);
    }
    setSubtitle(s.text);
    onSpeaking?.(true);
    h.stopSpeaking();
    h.speakAudio({ audio, ...timing }, { lipsyncLang: "ru" });
    window.setTimeout(() => { if (spoken.current === s.id) { setSubtitle(""); setBusy(false); onSpeaking?.(false); } }, audio.duration * 1000 + 800);
  };

  useEffect(() => {
    if (!say) return;
    if (ready) speak(say); else pending.current = say;
  }, [say?.id, ready]);
  useEffect(() => { if (ready && pending.current) { speak(pending.current); pending.current = null; } }, [ready]);

  return (
    <div className="avatar-stage">
      <div ref={node} className="avatar-canvas" />
      {!ready && <div className="avatar-over muted small">Загружаем 3D-собеседника… {progress > 0 && `${progress}%`}</div>}
      {busy && !subtitle && <div className="avatar-over muted small">Готовит ответ…</div>}
      {subtitle && <div className="subtitle">{subtitle}</div>}
      {note && !subtitle && <p className="small muted avatar-note">{note}</p>}
      {!ttsReady && ready && <span className="mute-tag" title="Озвучка не настроена: собеседник двигает губами без звука, реплика видна субтитром">Без звука</span>}
    </div>
  );
}
