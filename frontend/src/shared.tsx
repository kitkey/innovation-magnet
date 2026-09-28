import { api, fmtValue, Message, Scenario, ScenarioCard, SessionView, store, TurnOut } from "./api";

export type View = { name: "list" } | { name: "setup"; scenario?: Scenario; copy?: boolean } | { name: "dialog"; sid: string } | { name: "result"; sid: string } | { name: "history" } | { name: "test" }
  | { name: "auth" } | { name: "profile" } | { name: "org" } | { name: "leaderboard" };
export type Go = (v: View) => void;

export const OUTCOME: Record<string, string> = {
  agreement_in_zone: "Соглашение в целевой зоне",
  agreement_out_of_zone: "Соглашение вне целевой зоны",
  walk_away: "Рациональный выход к альтернативе",
  breakdown: "Срыв переговоров",
  turn_limit: "Лимит ходов",
  user_finished: "Завершено пользователем",
};

/** Метка исхода цветом: зелёная — цель достигнута, красная — нет, серая — без итога. */
export function outcomeTone(outcome: string | null, walkOk?: boolean | null): "good" | "bad" | "" {
  if (outcome === "agreement_in_zone" || (outcome === "walk_away" && walkOk)) return "good";
  if (outcome === "agreement_out_of_zone" || outcome === "breakdown" || (outcome === "walk_away" && walkOk === false)) return "bad";
  return "";
}

export const RU: Record<string, string> = { easy: "лёгкая", medium: "средняя", hard: "сложная", spin: "SPIN", harvard: "Гарвардский", batna: "BATNA", free: "свободный", cooperative: "сотрудничающий", avoiding: "уклоняющийся", pressing: "давящий", emotional: "эмоциональный" };
export const STYLE_RU: Record<string, string> = { hard: "жёсткий" };
export const METHOD_ICON: Record<string, string> = { batna: "fork", harvard: "scales", spin: "ask", free: "chat" };
export const DOMAIN_ICON: Record<string, string> = { "Закупки": "box", "Работа в команде": "users", "Проектная работа": "clip", "Работа с резидентами": "factory", "Карьера": "case" };

export const LABEL_RU: Record<string, string> = {
  interest_question: "вопрос об интересах", spin_situation: "ситуационный вопрос", spin_problem: "проблемный вопрос",
  spin_implication: "извлекающий вопрос", spin_need_payoff: "направляющий вопрос", objective_criterion: "объективный критерий",
  option_generation: "варианты", concrete_offer: "конкретное предложение", concession: "уступка", empathy: "эмпатия",
  argument: "аргумент", mandatory_detail: "обязательная деталь", pressure: "давление", personal_attack: "переход на личности",
  vague: "общая фраза", accept: "согласие", manipulation: "манипуляция",
  batna_reference: "сравнение с альтернативой", boundary: "граница", conditional_trade: "обмен условиями", walk_away: "выход к альтернативе",
};
export const BAD_LABELS = new Set(["pressure", "personal_attack", "vague", "manipulation", "concession"]);
const NEUTRAL_LABELS = new Set(["accept", "argument", "mandatory_detail"]);

export const ACTIVE_KEY = "arena.activeSid";
export const TEST_KEY = "arena.test";

export const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

/** «Ирина Белозёрова · Руководитель отдела…»; без имени — только роль. */
export function who(card: ScenarioCard): string {
  return card.opponent_name?.trim() ? `${card.opponent_name.trim()} · ${card.opponent_role}` : card.opponent_role;
}
export const oppName = (card: ScenarioCard) => card.opponent_name?.trim() || card.opponent_role;
export const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("");

export async function startScenario(id: string, go: Go, setErr: (e: string) => void) {
  try { go({ name: "dialog", sid: (await api.start(id)).session_id }); } catch (e) { setErr(`Не удалось начать сессию: ${(e as Error).message}`); }
}

export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n) % 100, b = a % 10;
  return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many;
}

/** Сервер пишет время в UTC; SQLite отдаёт его без зоны. */
export function parseAt(at?: string | null): Date | null {
  if (!at) return null;
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at : `${at}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}
export const hhmm = (d: Date | null) => (d ? d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "");
export function dayLabel(d: Date | null): string {
  if (!d) return "";
  const now = new Date();
  const days = Math.round((new Date(now.toDateString()).getTime() - new Date(d.toDateString()).getTime()) / 86400000);
  if (days === 0) return `сегодня, ${hhmm(d)}`;
  if (days === 1) return `вчера, ${hhmm(d)}`;
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

type State = TurnOut["state"];
type Thresholds = SessionView["thresholds"];
const clamp = (x: number) => Math.round(Math.max(0, Math.min(1, x)) * 100);

/** Шкалы собеседника в процентах, как их видит игрок. */
export function meters(st: State, t: Thresholds) {
  return {
    trust: clamp((st.trust - t.breakdown_trust) / (10 - t.breakdown_trust)),
    patience: clamp(1 - st.irritation / t.breakdown_irritation),
    readiness: clamp(st.readiness / t.concede),
  };
}
export const METER_RU = { trust: "доверие", patience: "терпение", readiness: "готовность уступить" } as const;

/** Состояние до и после каждого хода игрока: из реплик сессии, начальное — из initial_state. */
export function turnStates(s: SessionView): { before: State | null; after: State | null }[] {
  let prev: State | null = s.initial_state ?? null;
  return s.messages.filter((m) => m.role === "user").map((m) => {
    const r = { before: prev, after: m.state ?? null };
    prev = m.state ?? null;
    return r;
  });
}

export function Delta({ d }: { d: number }) {
  return <em className={`dlt ${d > 0 ? "up" : "down"}`}>{d > 0 ? `+${d}` : `−${-d}`}</em>;
}

/** Приёмы хода и сдвиги шкал «за ход». */
export function Marks({ m, before, after, card, t, hinted }: { m: Message; before: State | null; after: State | null; card: ScenarioCard; t: Thresholds; hinted?: boolean }) {
  const shifts: [string, number][] = [];
  if (before && after) {
    const a = meters(before, t), b = meters(after, t);
    (Object.keys(METER_RU) as (keyof typeof METER_RU)[]).forEach((k) => { if (b[k] !== a[k]) shifts.push([METER_RU[k], b[k] - a[k]]); });
  }
  const moved = before && after && before.position !== after.position;
  if (!m.labels.length && !shifts.length && !moved && !hinted) return null;
  return (
    <div className="marks">
      {m.labels.map((l) => <span key={l} className={`lab ${BAD_LABELS.has(l) && !(l === "concession" && m.labels.includes("conditional_trade")) ? "bad" : NEUTRAL_LABELS.has(l) ? "neu" : ""}`}>{LABEL_RU[l] ?? l}</span>)}
      {(shifts.length > 0 || moved) && <>
        {m.labels.length > 0 && <span className="sep" />}
        <span className="dl">за ход: {shifts.map(([n, d], i) => <span key={n}>{i > 0 && " · "}{n} <Delta d={d} /></span>)}
          {moved && <>{shifts.length > 0 && " · "}позиция собеседника <b>{fmtValue(before!.position, card.target_zone.unit)} → {fmtValue(after!.position, card.target_zone.unit)}</b></>}
        </span>
      </>}
      {hinted && <span className="hintref">подсказка маскота</span>}
    </div>
  );
}

/** Рекомендованный сценарий по входному тесту. */
export type Weak = "interests" | "criteria" | "emotions" | "offers" | "batna";
export const WEAK_RU: Record<Weak, string> = { interests: "выяснение интересов", criteria: "объективные критерии", emotions: "контроль эмоций", offers: "уступки и обмен условиями", batna: "альтернатива и граница сделки" };
export const WEAK_METHOD: Record<Weak, string> = { interests: "spin", criteria: "harvard", emotions: "harvard", offers: "batna", batna: "batna" };
export function testResult(): { level: string; weak: Weak | null } | null {
  try { const v = JSON.parse(store.get(TEST_KEY) ?? "null"); return v && v.level ? v : null; } catch { return null; }
}
export function recommend(items: Scenario[], level: string, weak: Weak | null): Scenario | undefined {
  return items.find((s) => s.difficulty === level && (!weak || s.method === WEAK_METHOD[weak])) ?? items.find((s) => s.difficulty === level) ?? items[0];
}

const MULT: Record<string, number> = { easy: 0.8, medium: 1, hard: 1.25 };
/** Балл сессии, как на сервере (scoring.session_score). */
export function sessionScore(axes: Record<string, number> | undefined, difficulty: string, outcome: string | null, walkOk: boolean): number | null {
  const v = Object.values(axes ?? {});
  if (!v.length) return null;
  const bonus = outcome === "agreement_in_zone" || (outcome === "walk_away" && walkOk);
  return Math.round((v.reduce((a, b) => a + b, 0) / v.length) * (MULT[difficulty] ?? 1) + (bonus ? 10 : 0));
}
