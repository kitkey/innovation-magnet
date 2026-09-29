import { type PointerEvent, useEffect, useRef, useState } from "react";
import { MicIcon, SendIcon, StopIcon, TrashIcon } from "../icons";
import { pickMime, toWav16k } from "./wav";

// Голосовое как в Telegram: удержание пишет, отпускание отправляет, сдвиг влево отменяет.
// Короткое нажатие включает запись без удержания: «Стоп» → прослушать, удалить или отправить.
type Props = { disabled: boolean; sttReady: boolean; maxSeconds: number; onSend: (wav: Blob) => Promise<boolean>; onError: (msg: string) => void };
type Rec = { mr: MediaRecorder; stream: MediaStream; chunks: Blob[]; after: "send" | "preview" | "cancel" };

const HOLD_MS = 400;
const CANCEL_PX = 80;
export const STT_OFF = "Распознавание речи не настроено: администратору нужно задать YANDEX_API_KEY. Пока отвечайте текстом.";

function micError(e: unknown): string {
  const name = (e as DOMException)?.name;
  if (!window.isSecureContext) return "Микрофон работает только по https или на localhost";
  if (name === "NotAllowedError" || name === "SecurityError") return "Нет доступа к микрофону: разрешите его в настройках браузера";
  if (name === "NotFoundError") return "Микрофон не найден";
  return `Не удалось включить микрофон: ${(e as Error)?.message ?? e}`;
}

export default function Recorder({ disabled, sttReady, maxSeconds, onSend, onError }: Props) {
  const rec = useRef<Rec | null>(null);
  const press = useRef<{ t: number; x: number; up: boolean } | null>(null);
  const [state, setState] = useState<"idle" | "hold" | "locked" | "processing" | "preview">("idle");
  const [elapsed, setElapsed] = useState(0);
  const [shift, setShift] = useState(0);
  const [preview, setPreview] = useState<{ wav: Blob; url: string } | null>(null);

  useEffect(() => {
    if (state !== "hold" && state !== "locked") return;
    const t0 = Date.now();
    const id = window.setInterval(() => {
      const s = (Date.now() - t0) / 1000;
      setElapsed(s);
      if (s >= maxSeconds) stop(state === "hold" ? "send" : "preview");
    }, 200);
    return () => window.clearInterval(id);
  }, [state]);
  useEffect(() => () => { rec.current?.stream.getTracks().forEach((t) => t.stop()); if (preview) URL.revokeObjectURL(preview.url); }, []);

  const finish = async (r: Rec) => {
    r.stream.getTracks().forEach((t) => t.stop());
    rec.current = null;
    if (r.after === "cancel" || !r.chunks.length) { setState("idle"); return; }
    setState("processing");
    try {
      const { wav, seconds } = await toWav16k(new Blob(r.chunks, { type: r.mr.mimeType }));
      if (seconds < 0.5) { setState("idle"); onError("Слишком короткая запись: удерживайте кнопку, пока говорите"); return; }
      if (r.after === "send") { await onSend(wav); setState("idle"); return; }
      setPreview({ wav, url: URL.createObjectURL(wav) });
      setState("preview");
    } catch (e) {
      setState("idle");
      onError(`Не удалось обработать запись: ${(e as Error).message}`);
    }
  };

  const begin = async (mode: "hold" | "locked") => {
    if (!sttReady) { onError(STT_OFF); return; }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") { onError("Браузер не умеет записывать звук, ответьте текстом"); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
      const mime = pickMime();
      const mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      const r: Rec = { mr, stream, chunks: [], after: "preview" };
      mr.ondataavailable = (e) => { if (e.data.size) r.chunks.push(e.data); };
      mr.onstop = () => finish(r);
      rec.current = r;
      mr.start(250);
      setElapsed(0); setShift(0);
      // Кнопку отпустили, пока браузер спрашивал разрешение, — продолжаем запись без удержания
      setState(mode === "hold" && press.current?.up ? "locked" : mode);
    } catch (e) { onError(micError(e)); setState("idle"); }
  };

  const stop = (after: Rec["after"]) => {
    const r = rec.current;
    if (!r) return;
    r.after = after;
    if (r.mr.state !== "inactive") r.mr.stop(); else finish(r);
  };

  const discard = () => { if (preview) URL.revokeObjectURL(preview.url); setPreview(null); setState("idle"); };
  const sendPreview = async () => {
    if (!preview) return;
    setState("processing");
    const ok = await onSend(preview.wav);
    if (ok) discard(); else setState("preview");
  };

  const down = (e: PointerEvent<HTMLButtonElement>) => {
    if (disabled || state !== "idle") return;
    e.currentTarget.setPointerCapture(e.pointerId);
    press.current = { t: Date.now(), x: e.clientX, up: false };
    begin("hold");
  };
  const move = (e: PointerEvent) => {
    if (state !== "hold" || !press.current) return;
    const dx = Math.max(0, press.current.x - e.clientX);
    setShift(dx);
    if (dx > CANCEL_PX) { press.current = null; stop("cancel"); }
  };
  const up = () => {
    const p = press.current;
    if (!p) return;
    p.up = true;
    if (state !== "hold") return;
    press.current = null;
    if (Date.now() - p.t < HOLD_MS) setState("locked"); else stop("send");
  };

  const time = `${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, "0")}`;
  if (state === "preview" && preview) return (
    <div className="recorder">
      <audio controls src={preview.url} />
      <button title="Удалить" aria-label="Удалить запись" onClick={discard}><TrashIcon /></button>
      <button className="primary" title="Отправить" aria-label="Отправить голосовое" disabled={disabled} onClick={sendPreview}><SendIcon /></button>
    </div>
  );
  return (
    <div className="recorder">
      {state === "hold" && <span className="rec-hint"><i className="rec-dot" />{time} · отпустите, чтобы отправить · влево — отмена{shift > 20 && ` (${Math.min(100, Math.round((100 * shift) / CANCEL_PX))}%)`}</span>}
      {state === "locked" && <>
        <span className="rec-hint"><i className="rec-dot" />{time} · запись до {maxSeconds} с</span>
        <button title="Отменить" aria-label="Отменить запись" onClick={() => stop("cancel")}><TrashIcon /></button>
        <button title="Остановить" aria-label="Остановить запись" onClick={() => stop("preview")}><StopIcon /></button>
      </>}
      {state === "processing" && <span className="rec-hint muted">Обрабатываем запись…</span>}
      {(state === "idle" || state === "hold") && (
        <button className={`mic ${state === "hold" ? "on" : ""} ${sttReady ? "" : "off"}`} disabled={disabled}
          title={sttReady ? "Удерживайте, чтобы записать; короткое нажатие — запись без удержания" : STT_OFF} aria-label="Голосовое сообщение"
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => { press.current = null; stop("cancel"); }}
          onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && state === "idle") { e.preventDefault(); begin("locked"); } }}
          onContextMenu={(e) => e.preventDefault()}>
          <MicIcon />
        </button>
      )}
    </div>
  );
}
