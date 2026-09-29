// Тайминги слов, когда озвучки нет: длительность слова по числу букв, паузы на знаках препинания.
export type Timings = { words: string[]; wtimes: number[]; wdurations: number[]; total: number };

export function estimateTimings(text: string): Timings {
  const out: Timings = { words: [], wtimes: [], wdurations: [], total: 0 };
  let t = 150;
  for (const token of text.split(/\s+/)) {
    const letters = token.replace(/[^\p{L}\p{N}]/gu, "");
    if (!letters) continue;
    const d = Math.max(180, letters.length * 70);
    out.words.push(token); out.wtimes.push(t); out.wdurations.push(d);
    t += d + (/[.!?…]$/.test(token) ? 350 : /[,;:—-]$/.test(token) ? 180 : 60);
  }
  out.total = t + 300;
  return out;
}

// Реплика кусками для субтитра: по предложениям, длинное предложение делится по словам (лучше на запятой) до max символов.
export function subtitleChunks(text: string, max: number): { text: string; words: number }[] {
  const out: { text: string; words: number }[] = [];
  const push = (t: string) => { const w = t.split(/\s+/).filter((x) => /[\p{L}\p{N}]/u.test(x)).length; if (t) out.push({ text: t, words: w }); };
  for (const raw of text.match(/[^.!?…]+(?:[.!?…]+["»)]*|$)/g) ?? [text]) {
    const sen = raw.trim();
    if (!sen) continue;
    if (sen.length <= max) { push(sen); continue; }
    const per = sen.length / Math.ceil(sen.length / max);
    let cur = "";
    for (const w of sen.split(/\s+/)) {
      if (cur && (cur.length + 1 + w.length > Math.min(max, per * 1.2) || (cur.length > per * 0.6 && /[,;:—]$/.test(cur)))) { push(cur); cur = w; }
      else cur = cur ? `${cur} ${w}` : w;
    }
    push(cur);
  }
  return out;
}

export function b64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}

export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGL2RenderingContext && c.getContext("webgl2")) || !!c.getContext("webgl");
  } catch { return false; }
}
