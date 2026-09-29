// Русский липсинк для TalkingHead: буквы → виземы Oculus. Сделан по образцу lipsync-fi.mjs:
// русское письмо почти фонетическое, ударение на форму рта почти не влияет, поэтому хватает таблицы букв.
// Йотированные я, е, ё, ю в начале слова и после гласной, ь, ъ дают «й» (I) + гласную; после согласной только гласную.

const VISEMES: Record<string, string> = {
  а: "aa", о: "O", у: "U", ы: "I", э: "E", и: "I",
  б: "PP", п: "PP", м: "PP", в: "FF", ф: "FF",
  т: "DD", д: "DD", н: "nn", л: "nn",
  с: "SS", з: "SS", ц: "SS", ш: "CH", ж: "CH", щ: "CH", ч: "CH",
  к: "kk", г: "kk", х: "kk", р: "RR", й: "I",
  a: "aa", e: "E", i: "I", o: "O", u: "U", y: "I", b: "PP", c: "SS", d: "DD", f: "FF", g: "kk", h: "kk", j: "I", k: "kk",
  l: "nn", m: "PP", n: "nn", p: "PP", q: "kk", r: "RR", s: "SS", t: "DD", v: "FF", w: "U", x: "SS", z: "SS",
};
const IOTATED: Record<string, string> = { я: "aa", е: "E", ё: "O", ю: "U" };
const VOWELS = new Set([..."аоуыэияеёюaeiouy"]);
const SKIP = new Set(["ь", "ъ"]);

// Относительные длительности визем (1 = средняя), как в финском модуле
const DURATIONS: Record<string, number> = { aa: 0.95, E: 0.9, I: 0.92, O: 0.96, U: 0.95, PP: 1.08, SS: 1.23, DD: 1.05, FF: 1, kk: 1.21, nn: 0.88, RR: 0.88, CH: 1.15, sil: 1 };
const PAUSES: Record<string, number> = { " ": 1, ",": 3, "-": 0.5 };

const ONES = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять", "одиннадцать", "двенадцать", "тринадцать",
  "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"];
const TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"];
const HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"];
const SCALES: [number, [string, string, string]][] = [[1e9, ["миллиард", "миллиарда", "миллиардов"]], [1e6, ["миллион", "миллиона", "миллионов"]], [1e3, ["тысяча", "тысячи", "тысяч"]]];
const SYMBOLS: Record<string, string> = { "%": "процентов", "₽": "рублей", "$": "долларов", "€": "евро", "+": "плюс", "&": "и" };

function plural(n: number, [one, few, many]: [string, string, string]) {
  const d = n % 10, dd = n % 100;
  return d === 1 && dd !== 11 ? one : d >= 2 && d <= 4 && (dd < 12 || dd > 14) ? few : many;
}

function below1000(n: number, feminine = false): string[] {
  const w: string[] = [];
  if (n >= 100) { w.push(HUNDREDS[Math.floor(n / 100)]); n %= 100; }
  if (n >= 20) { w.push(TENS[Math.floor(n / 10)]); n %= 10; }
  if (n > 0 || !w.length) w.push(feminine && n === 1 ? "одна" : feminine && n === 2 ? "две" : ONES[n]);
  return w;
}

export function numberToWords(x: string): string {
  let n = Math.floor(Math.abs(parseInt(x, 10)));
  if (!Number.isFinite(n)) return x;
  if (n === 0) return ONES[0];
  const w: string[] = [];
  for (const [scale, forms] of SCALES) {
    if (n >= scale) {
      const k = Math.floor(n / scale);
      w.push(...below1000(k % 1000, scale === 1e3), plural(k % 1000, forms));
      n %= scale;
    }
  }
  if (n > 0) w.push(...below1000(n));
  return w.join(" ");
}

type Lipsync = { words: string; visemes: string[]; times: number[]; durations: number[] };

export class LipsyncRu {
  preProcessText(s: string): string {
    return s.replace(/[#_*'"«»:;()!?.…]/g, " ")
      .replace(/[%₽$€+&]/g, (c) => ` ${SYMBOLS[c]} `)
      .replace(/(\d)[,.](\d)/g, "$1 запятая $2")
      .replace(/(\d)\s(?=\d{3}\b)/g, "$1")
      .replace(/\d+/g, (d) => numberToWords(d))
      .replace(/\s+/g, " ")
      .trim();
  }

  wordsToVisemes(w: string): Lipsync {
    const o: Lipsync = { words: w, visemes: [], times: [], durations: [] };
    let t = 0;
    const push = (v: string) => {
      const last = o.visemes.length - 1;
      if (last >= 0 && o.visemes[last] === v) {
        const d = 0.7 * (DURATIONS[v] ?? 1);
        o.durations[last] += d; t += d;
      } else {
        const d = DURATIONS[v] ?? 1;
        o.visemes.push(v); o.times.push(t); o.durations.push(d); t += d;
      }
    };
    const chars = [...w.toLowerCase()];
    chars.forEach((c, i) => {
      const prev = chars[i - 1];
      if (c in IOTATED) {
        if (prev === undefined || prev === " " || VOWELS.has(prev) || SKIP.has(prev)) push("I");
        push(IOTATED[c]);
      } else if (VISEMES[c]) push(VISEMES[c]);
      else if (!SKIP.has(c)) t += PAUSES[c] ?? 0;
    });
    return o;
  }
}
