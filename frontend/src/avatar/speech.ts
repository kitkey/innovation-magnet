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
