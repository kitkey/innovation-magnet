import { SyntheticEvent, useEffect, useState } from "react";
import { Auth, Leaderboard, OrgCabinet, Profile, UserIcon } from "./account";
import { api, AUTH_KEY, editKeys, fmtValue, Hint, HintOut, Message, MODE_KEY, Scenario, ScenarioCard, SessionResult, SessionView, store, TurnOut, unitParts, User, VoiceStatus } from "./api";
import type { Say } from "./avatar/Avatar3D";
import { CoachCorner, CoachPanel, coachTips } from "./Coach";
import { MicIcon } from "./icons";
import OpponentAvatar, { OpponentMode } from "./OpponentAvatar";
import Recorder from "./voice/Recorder";

type View = { name: "list" } | { name: "setup"; scenario?: Scenario; copy?: boolean } | { name: "dialog"; sid: string } | { name: "result"; sid: string } | { name: "history" } | { name: "test" }
  | { name: "auth" } | { name: "profile" } | { name: "org" } | { name: "leaderboard" };
type Go = (v: View) => void;

const OUTCOME: Record<string, string> = {
  agreement_in_zone: "Соглашение в целевой зоне",
  agreement_out_of_zone: "Соглашение вне целевой зоны",
  walk_away: "Рациональный выход к альтернативе",
  breakdown: "Срыв переговоров",
  turn_limit: "Лимит ходов",
  user_finished: "Завершено пользователем",
};

const RU: Record<string, string> = { easy: "лёгкая", medium: "средняя", hard: "сложная", spin: "SPIN", harvard: "Гарвардский", batna: "BATNA", free: "свободный", cooperative: "сотрудничающий", avoiding: "уклоняющийся", pressing: "давящий", emotional: "эмоциональный" };
const STYLE_RU: Record<string, string> = { hard: "жёсткий" };

const LABEL_RU: Record<string, string> = {
  interest_question: "вопрос об интересах", spin_situation: "ситуационный вопрос", spin_problem: "проблемный вопрос",
  spin_implication: "извлекающий вопрос", spin_need_payoff: "направляющий вопрос", objective_criterion: "объективный критерий",
  option_generation: "варианты", concrete_offer: "конкретное предложение", concession: "уступка", empathy: "эмпатия",
  argument: "аргумент", mandatory_detail: "обязательная деталь", pressure: "давление", personal_attack: "переход на личности",
  vague: "общая фраза", accept: "согласие", manipulation: "манипуляция",
  batna_reference: "сравнение с альтернативой", boundary: "граница", conditional_trade: "обмен условиями", walk_away: "выход к альтернативе",
};
const BAD_LABELS = new Set(["pressure", "personal_attack", "vague", "manipulation"]);

const ACTIVE_KEY = "arena.activeSid";
const TEST_KEY = "arena.test";

const EMPTY: ScenarioCard = {
  name: "", domain: "", topic: "", difficulty: "medium", tone: "neutral", method: "free", style: "hard",
  user_role: "", user_goal: "", opponent_role: "", opponent_name: "", opponent_goal: "", opponent_hidden_interests: [],
  opponent_batna: "", user_batna: "", target_zone: { unit: "", user_start: 0, zone_min: 0, zone_max: 0, opponent_start: 0 },
  mandatory_details: [], context: "", opening: "", max_turns: 10, locked_by_org: false, voice: "female", avatar_url: null,
  coach_tips: [], hints: [],
};

/** «Ирина Белозёрова · Руководитель отдела…»; без имени — только роль. */
export function who(card: ScenarioCard): string {
  return card.opponent_name?.trim() ? `${card.opponent_name.trim()} · ${card.opponent_role}` : card.opponent_role;
}

export default function App() {
  const [view, setView] = useState<View>(() => (store.get(TEST_KEY) ? { name: "list" } : { name: "test" }));
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    if (store.get(AUTH_KEY)) api.me().then(setUser).catch(() => store.set(AUTH_KEY, null));
  }, []);
  const onUser = (u: User | null) => { setUser(u); setView(u ? { name: "profile" } : { name: "list" }); };
  return (
    <div className="app">
      <header>
        <b onClick={() => setView({ name: "list" })}>Арена переговоров</b>
        <nav>
          <button onClick={() => setView({ name: "list" })}>Сценарии</button>
          <button onClick={() => setView({ name: "setup" })}>Новый сценарий</button>
          <button onClick={() => setView({ name: "history" })}>История</button>
          <button onClick={() => setView({ name: "leaderboard" })}>Лидерборд</button>
          {user?.role === "org_admin" && <button onClick={() => setView({ name: "org" })}>Организация</button>}
          <button onClick={() => setView({ name: "test" })}>Входной тест</button>
          <button className="user" onClick={() => setView(user ? { name: "profile" } : { name: "auth" })}><UserIcon />{user ? user.display_name : "Войти"}</button>
        </nav>
      </header>
      {view.name === "list" && <List key={user?.id ?? "guest"} user={user} go={setView} />}
      {view.name === "setup" && <Setup key={`${view.scenario?.id ?? "new"}-${view.copy ? "copy" : "edit"}`} scenario={view.scenario} copy={view.copy} go={setView} />}
      {view.name === "dialog" && <Dialog key={view.sid} sid={view.sid} go={setView} />}
      {view.name === "result" && <Result key={view.sid} sid={view.sid} go={setView} />}
      {view.name === "history" && <History go={setView} />}
      {view.name === "test" && <EntryTest go={setView} />}
      {view.name === "auth" && <Auth onUser={onUser} />}
      {view.name === "profile" && (user ? <Profile user={user} onUser={(u) => (u ? setUser(u) : onUser(null))} /> : <Auth onUser={onUser} />)}
      {view.name === "org" && (user?.role === "org_admin" ? <OrgCabinet key={user.org_id} user={user} onUser={setUser} /> : <main><p className="muted">Кабинет доступен администратору организации.</p></main>)}
      {view.name === "leaderboard" && <Leaderboard key={user?.id ?? "guest"} user={user} />}
    </div>
  );
}

async function startScenario(id: string, go: Go, setErr: (e: string) => void) {
  try { go({ name: "dialog", sid: (await api.start(id)).session_id }); } catch (e) { setErr(`Не удалось начать сессию: ${(e as Error).message}`); }
}

function List({ user, go }: { user: User | null; go: Go }) {
  const [items, setItems] = useState<Scenario[]>([]);
  const [active, setActive] = useState<SessionView | null>(null);
  const [err, setErr] = useState("");
  const keys = editKeys.all();
  const canEdit = (s: Scenario) => s.can_edit || !!keys[s.id];
  useEffect(() => {
    api.scenarios().then(setItems).catch((e) => setErr(`Сценарии не загрузились: ${e.message}`));
    const sid = store.get(ACTIVE_KEY);
    if (sid) api.session(sid).then((s) => (s.status === "active" ? setActive(s) : store.set(ACTIVE_KEY, null))).catch(() => store.set(ACTIVE_KEY, null));
  }, []);
  return (
    <main className="cards">
      {active && (
        <div className="banner">
          <span>Есть незавершённая сессия «{active.card.name}», ход {active.turn}/{active.max_turns}.</span>
          <div className="row">
            <button className="primary" onClick={() => go({ name: "dialog", sid: active.id })}>Продолжить</button>
            <button onClick={() => { store.set(ACTIVE_KEY, null); setActive(null); }}>Скрыть</button>
          </div>
        </div>
      )}
      {err && <p className="error">{err}</p>}
      {items.map((s) => (
        <article key={s.id} className="card">
          <h3>{s.name}</h3>
          <p className="muted">{s.domain} · {RU[s.difficulty]} · метод: {RU[s.method]} · стиль: {STYLE_RU[s.style] ?? RU[s.style]}</p>
          <p>{s.topic}</p>
          <div className="row">
            <button className="primary" onClick={() => startScenario(s.id, go, setErr)}>Начать</button>
            {canEdit(s)
              ? <button onClick={() => go({ name: "setup", scenario: s })}>Настроить</button>
              : <button title={s.builtin ? "Встроенный сценарий не меняется, настройки сохранятся в вашу копию" : "Сценарий чужой, настройки сохранятся в вашу копию"}
                onClick={() => go({ name: "setup", scenario: s, copy: true })}>Сделать копию</button>}
          </div>
        </article>
      ))}
    </main>
  );
}

function AvatarField({ value, onChange }: { value: string | null; onChange: (url: string | null) => void }) {
  const [info, setInfo] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const upload = async (f: File | undefined) => {
    if (!f) return;
    setErr(""); setInfo(""); setBusy(true);
    try {
      const r = await api.uploadAvatar(f);
      onChange(r.url);
      setInfo(`Загружено: ${(r.size / 1048576).toFixed(1)} МБ, визем ${r.visemes}. ${r.warnings.join(". ")}`);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <fieldset><legend>3D-аватар собеседника</legend>
      <p className="small muted">{value ? `Свой аватар: ${value}` : "Стандартный аватар (MPFB, CC0)."} GLB со скелетом в стиле Mixamo, виземами Oculus и ARKit-блендшейпами: Avaturn, VRoid через Blender, MPFB. Как сделать — в README.</p>
      <div className="row">
        <label className="file">{busy ? "Загружаем…" : "Загрузить GLB"}<input type="file" accept=".glb,model/gltf-binary" disabled={busy} onChange={(e) => upload(e.target.files?.[0])} /></label>
        {value && <button onClick={() => onChange(null)}>Вернуть стандартный</button>}
      </div>
      {info && <p className="small">{info}</p>}
      {err && <p className="error">{err}</p>}
    </fieldset>
  );
}

const HINT_LABELS = ["pressure", "concession", "personal_attack", "manipulation", "vague", "batna_reference", "boundary", "conditional_trade", "concrete_offer", "empathy", "interest_question", "objective_criterion"];
const HINT_MISSING = ["interest_question", "objective_criterion", "batna_reference", "conditional_trade", "concrete_offer", "boundary", "empathy", "mandatory_detail", "spin_problem", "spin_implication", "spin_need_payoff"];
const HINT_KINDS: [string, string][] = [
  ...HINT_LABELS.map((l): [string, string] => [`label:${l}`, `В ходе игрока: ${LABEL_RU[l]}`]),
  ...HINT_MISSING.map((l): [string, string] => [`missing:${l}`, `К ходу N ни разу не было: ${LABEL_RU[l]}`]),
  ["irritation_high", "Собеседник на грани срыва"], ["trust_low", "Доверие упало"], ["readiness_high", "Собеседник почти готов уступить"],
  ["turns_left", "Осталось N ходов или меньше"],
];

/** «missing:empathy@3» → вид условия «missing:empathy» и число 3. */
function splitWhen(when: string): { kind: string; n: number } {
  const m = when.match(/^(missing:[a-z_]+)@(\d+)$/) ?? when.match(/^(turns_left):(\d+)$/);
  return m ? { kind: m[1], n: Number(m[2]) } : { kind: when, n: 0 };
}

function joinWhen(kind: string, n: number): string {
  if (kind.startsWith("missing:")) return `${kind}@${n || 3}`;
  if (kind === "turns_left") return `turns_left:${n || 2}`;
  return kind;
}

function HintsField({ value, maxTurns, onChange }: { value: Hint[]; maxTurns: number; onChange: (v: Hint[]) => void }) {
  const put = (i: number, h: Hint) => onChange(value.map((x, k) => (k === i ? h : x)));
  return (
    <fieldset className="hints-field"><legend>Подсказки по ходу диалога</legend>
      <p className="small muted">Маскот покажет подсказку один раз, когда выполнится условие. Стандартные подсказки по методу работают всегда, ваши показываются первыми.</p>
      {value.map((h, i) => {
        const { kind, n } = splitWhen(h.when);
        const needsN = kind.startsWith("missing:") || kind === "turns_left";
        return (
          <div key={i} className="hint-row">
            <label>Когда
              <div className="hint-when">
                <select value={kind} onChange={(e) => put(i, { ...h, when: joinWhen(e.target.value, n) })}>
                  {HINT_KINDS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </select>
                {needsN && <input type="number" min={1} max={maxTurns} value={n} aria-label="N" onChange={(e) => put(i, { ...h, when: joinWhen(kind, Number(e.target.value)) })} />}
              </div>
            </label>
            <label>Текст подсказки<input value={h.text} maxLength={300} placeholder="Одна-две строки: что сделать иначе" onChange={(e) => put(i, { ...h, text: e.target.value })} /></label>
            <button className="hint-del" title="Удалить подсказку" aria-label="Удалить подсказку" onClick={() => onChange(value.filter((_, k) => k !== i))}>
              <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" /></svg>
            </button>
          </div>
        );
      })}
      {value.length < 20 && <button className="add" onClick={() => onChange([...value, { when: "label:concession", text: "" }])}>Добавить подсказку</button>}
    </fieldset>
  );
}

function lines(v: string) { return v.split("\n").map((x) => x.trim()).filter(Boolean); }

function Setup({ scenario, copy, go }: { scenario?: Scenario; copy?: boolean; go: Go }) {
  const [card, setCard] = useState<ScenarioCard>(scenario ? (copy ? { ...scenario, name: `${scenario.name} (копия)`, locked_by_org: false } : scenario) : EMPTY);
  const [brief, setBrief] = useState("");
  const [err, setErr] = useState("");
  const [token, setToken] = useState(store.get("arena.adminToken") ?? "");
  const set = (k: keyof ScenarioCard, v: unknown) => setCard({ ...card, [k]: v });
  const setZone = (k: string, v: string) => setCard({ ...card, target_zone: { ...card.target_zone, [k]: k === "unit" ? v : Number(v) } });
  const saveToken = (v: string) => { setToken(v); store.set("arena.adminToken", v.trim() || null); };
  const save = async () => {
    setErr("");
    const clean = { ...card, coach_tips: (card.coach_tips ?? []).map((t) => t.trim()).filter(Boolean), hints: (card.hints ?? []).filter((h) => h.text.trim()) };
    try {
      const s = scenario && !copy ? await api.updateScenario(scenario.id, clean) : await api.createScenario(clean);
      await startScenario(s.id, go, setErr);
    } catch (e) { setErr((e as Error).message); }
  };
  const gen = async () => { setErr(""); try { const g = await api.generate(brief); setCard({ ...g, coach_tips: card.coach_tips, hints: card.hints }); } catch (e) { setErr((e as Error).message); } };
  const text = (k: keyof ScenarioCard, label: string, area = false) => (
    <label>{label}{area
      ? <textarea value={card[k] as string} onChange={(e) => set(k, e.target.value)} />
      : <input value={card[k] as string} onChange={(e) => set(k, e.target.value)} />}</label>
  );
  const select = (k: keyof ScenarioCard, label: string, opts: [string, string][]) => (
    <label>{label}<select value={card[k] as string} onChange={(e) => set(k, e.target.value)}>{opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>
  );
  return (
    <main className="form">
      <section className="gen">
        <textarea placeholder="Опишите свою ситуацию своими словами — LLM соберёт карточку" value={brief} onChange={(e) => setBrief(e.target.value)} />
        <button onClick={gen}>Сгенерировать карточку</button>
      </section>
      {text("name", "Название")}{text("domain", "Сфера")}{text("topic", "Тема")}
      {select("difficulty", "Сложность", [["easy", "Лёгкая"], ["medium", "Средняя"], ["hard", "Сложная"]])}
      {select("tone", "Тон", [["neutral", "Нейтральный"], ["friendly", "Дружелюбный"], ["strict", "Строгий"], ["skeptical", "Скептичный"]])}
      {select("method", "Метод, который тренируем", [["free", "Свободный"], ["spin", "SPIN"], ["harvard", "Гарвардский"], ["batna", "BATNA"]])}
      {select("style", "Стиль собеседника", [["hard", "Жёсткий"], ["cooperative", "Сотрудничающий"], ["avoiding", "Уклоняющийся"], ["pressing", "Давящий"], ["emotional", "Эмоциональный"]])}
      {text("user_role", "Ваша роль")}{text("user_goal", "Ваша цель", true)}
      {text("opponent_role", "Роль собеседника")}
      <label>Имя собеседника<input value={card.opponent_name ?? ""} maxLength={80} placeholder="Вымышленные имя и фамилия; если пусто, в диалоге будет роль" onChange={(e) => set("opponent_name", e.target.value)} /></label>
      {text("opponent_goal", "Цель собеседника", true)}
      <label>Скрытые интересы собеседника (по строке)<textarea value={card.opponent_hidden_interests.join("\n")} onChange={(e) => set("opponent_hidden_interests", lines(e.target.value))} /></label>
      {text("opponent_batna", "BATNA собеседника")}{text("user_batna", "Ваша BATNA")}
      <fieldset><legend>Целевая зона соглашения</legend>
        <label>Предмет и единица торга через запятую<input value={card.target_zone.unit} placeholder="стоимость доработки, тыс. руб." onChange={(e) => setZone("unit", e.target.value)} /></label>
        <label>Ваша стартовая позиция<input type="number" value={card.target_zone.user_start} onChange={(e) => setZone("user_start", e.target.value)} /></label>
        <label>Зона от<input type="number" value={card.target_zone.zone_min} onChange={(e) => setZone("zone_min", e.target.value)} /></label>
        <label>Зона до<input type="number" value={card.target_zone.zone_max} onChange={(e) => setZone("zone_max", e.target.value)} /></label>
        <label>Старт собеседника<input type="number" value={card.target_zone.opponent_start} onChange={(e) => setZone("opponent_start", e.target.value)} /></label>
        <p className="muted small">Зона лежит между стартовыми позициями сторон.</p>
      </fieldset>
      <label>Обязательные детали (по строке)<textarea value={card.mandatory_details.join("\n")} onChange={(e) => set("mandatory_details", lines(e.target.value))} /></label>
      {text("context", "Контекст", true)}
      <label>Первая реплика собеседника<textarea value={card.opening ?? ""} placeholder="Если пусто, собеседник начнёт сам: с сути вопроса и своей стартовой позиции"
        onChange={(e) => set("opening", e.target.value)} /></label>
      {select("voice", "Голос собеседника в режиме «3D и голос»", [["female", "Женский"], ["male", "Мужской"]])}
      <AvatarField value={card.avatar_url} onChange={(v) => set("avatar_url", v)} />
      <label>Наставления перед стартом (по строке)<textarea value={(card.coach_tips ?? []).join("\n")} placeholder="Маскот покажет их до первого хода, перед стандартными советами по методу"
        onChange={(e) => set("coach_tips", e.target.value.split("\n"))} /></label>
      <HintsField value={card.hints ?? []} maxTurns={card.max_turns} onChange={(v) => set("hints", v)} />
      <label>Лимит ходов<input type="number" value={card.max_turns} onChange={(e) => set("max_turns", Number(e.target.value))} /></label>
      <label className="check"><input type="checkbox" checked={card.locked_by_org} onChange={(e) => set("locked_by_org", e.target.checked)} />Зафиксировать для сотрудников организации</label>
      <label>Токен администратора (запасной способ; администратор организации фиксирует и меняет сценарии своей организации без токена)<input type="password" value={token} onChange={(e) => saveToken(e.target.value)} /></label>
      {err && <p className="error">{err}</p>}
      <button className="primary" onClick={save}>Сохранить и начать</button>
    </main>
  );
}

function Bar({ label, value, hint }: { label: string; value: number; hint: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="bar" title={hint}>
      <span>{label}</span>
      <div className="track"><div className={`fill ${pct < 30 ? "low" : ""}`} style={{ width: `${pct}%` }} /></div>
      <span className="small muted">{pct}%</span>
    </div>
  );
}

function Chips({ labels }: { labels: string[] }) {
  return <div className="chips">{labels.map((l) => <span key={l} className={`chip ${BAD_LABELS.has(l) ? "bad" : ""}`}>{LABEL_RU[l] ?? l}</span>)}</div>;
}

function VoiceMsg({ m }: { m: Message }) {
  return (
    <div className="msg user voice">
      <span className="voice-tag"><MicIcon size={14} />голосовое</span>
      {m.audio_url && <audio controls preload="none" src={m.audio_url} />}
      <div>{m.text}</div>
    </div>
  );
}

const BRIEF_KEY = "arena.briefClosed";
const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

/** Бриф перед диалогом: только то, что знает игрок. Скрытые интересы, альтернатива собеседника и целевая зона сюда не попадают. */
function Brief({ card }: { card: ScenarioCard }) {
  const [open, setOpen] = useState(() => store.get(BRIEF_KEY) !== "1");
  const { subject, short } = unitParts(card.target_zone.unit);
  const toggle = (e: SyntheticEvent<HTMLDetailsElement>) => { setOpen(e.currentTarget.open); store.set(BRIEF_KEY, e.currentTarget.open ? null : "1"); };
  return (
    <details className="brief" open={open} onToggle={toggle}>
      <summary>Ситуация{!open && <span className="muted"> · {card.user_role}</span>}</summary>
      {card.context && <p>{card.context}</p>}
      <dl>
        <dt>Ваша роль</dt><dd>{card.user_role}</dd>
        <dt>Собеседник</dt><dd>{who(card)}</dd>
        <dt>Ваша цель</dt><dd>{card.user_goal}</dd>
        {card.user_batna && <><dt>Ваша альтернатива</dt><dd>{card.user_batna}{card.method === "batna" && ". Если сделка хуже неё, можно выйти из переговоров."}</dd></>}
        <dt>Предмет торга</dt><dd>{cap(subject || card.topic)} ({short}); вы начинаете с {fmtValue(card.target_zone.user_start, card.target_zone.unit)}</dd>
      </dl>
    </details>
  );
}

function Dialog({ sid, go }: { sid: string; go: Go }) {
  const [s, setS] = useState<SessionView | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [mode, setModeState] = useState<OpponentMode>(() => (store.get(MODE_KEY) === "avatar" ? "avatar" : "text"));
  const [vs, setVs] = useState<VoiceStatus | null | undefined>(undefined);
  const [say, setSay] = useState<Say | null>(null);
  const [intro, setIntro] = useState(false);
  const [tipsOpen, setTipsOpen] = useState(false);
  const [hints, setHints] = useState<HintOut[]>([]);
  const setMode = (m: OpponentMode) => { setModeState(m); store.set(MODE_KEY, m); };
  useEffect(() => { api.voiceStatus().then(setVs).catch(() => setVs(null)); }, []);
  const load = () => api.session(sid).then((v) => {
    if (v.status !== "active") { store.set(ACTIVE_KEY, null); go({ name: "result", sid }); return; }
    store.set(ACTIVE_KEY, sid); setS(v);
    // Наставления маскота показываем перед каждым новым диалогом, до первого хода игрока
    if (v.turn === 0 && coachTips(v.coach).length) setIntro(true);
    const last = v.messages[v.messages.length - 1];
    if (last?.role === "opponent") setSay({ id: v.turn, text: last.text, mood: v.mood ?? "neutral" });
  }).catch((e) => setErr(`Сессия не загрузилась: ${e.message}`));
  useEffect(() => { load(); }, [sid]);

  const apply = (base: SessionView, user: Message, r: TurnOut) => {
    setS({
      ...base, turn: r.turn, status: r.status, outcome: r.outcome, state: r.state, mood: r.mood,
      messages: [...base.messages, user, { role: "opponent", text: r.opponent_message, labels: [] }],
    });
    setSay({ id: r.turn, text: r.opponent_message, mood: r.mood });
    if (r.hints?.length) setHints(r.hints);
    // В режиме 3D даём собеседнику договорить последнюю реплику, потом открываем разбор
    if (r.status === "finished") { store.set(ACTIVE_KEY, null); window.setTimeout(() => go({ name: "result", sid }), mode === "avatar" ? 6000 : 0); }
  };

  const send = async () => {
    if (!s || !msg.trim() || busy) return;
    const text = msg;
    setBusy(true); setErr("");
    setS({ ...s, messages: [...s.messages, { role: "user", text, labels: [] }] });
    try {
      const r = await api.turn(sid, text);
      setMsg("");
      apply(s, { role: "user", text, labels: r.analysis.labels }, r);
    } catch (e) {
      setS(s);
      setErr(`Ход не отправлен: ${(e as Error).message}. Попробуйте ещё раз.`);
    } finally { setBusy(false); }
  };

  const sendVoice = async (wav: Blob) => {
    if (!s || busy) return false;
    const local = URL.createObjectURL(wav);
    setBusy(true); setErr("");
    setS({ ...s, messages: [...s.messages, { role: "user", text: "Распознаём…", labels: [], audio_url: local, pending: true }] });
    try {
      const r = await api.voiceTurn(sid, wav, "voice.wav");
      apply(s, { role: "user", text: r.recognized, labels: r.analysis.labels, audio_url: r.audio_url ?? local }, r);
      return true;
    } catch (e) {
      setS(s);
      setErr(`Голосовое не отправлено: ${(e as Error).message}`);
      return false;
    } finally { setBusy(false); }
  };
  const finish = async () => {
    setBusy(true); setErr("");
    try { await api.finish(sid); store.set(ACTIVE_KEY, null); go({ name: "result", sid }); } catch (e) { setErr(`Не удалось завершить: ${(e as Error).message}`); } finally { setBusy(false); }
  };
  const undo = async () => {
    if (!s) return;
    setBusy(true); setErr("");
    try { const v = await api.rewind(sid, s.turn - 1); store.set(ACTIVE_KEY, v.id); go({ name: "dialog", sid: v.id }); } catch (e) { setErr(`Не удалось отменить ход: ${(e as Error).message}`); } finally { setBusy(false); }
  };

  if (!s) return <main>{err ? <p className="error">{err}</p> : <p>Загрузка…</p>}</main>;
  const t = s.thresholds;
  const lastUser = [...s.messages].reverse().find((m) => m.role === "user" && m.labels.length);
  const ready = !busy && s.status === "active" && !intro;
  const tips = coachTips(s.coach);
  const name = s.card.opponent_name?.trim() || s.card.opponent_role;
  return (
    <main className="dialog">
      <Brief card={s.card} />
      <div className="row between">
        <span className="opp-who"><b>{name}</b>{s.card.opponent_name?.trim() && <span className="muted"> · {s.card.opponent_role}</span>}</span>
        <div className="tabs">{([["text", "Текст"], ["avatar", "3D и голос"]] as [OpponentMode, string][]).map(([v, t]) => (
          <button key={v} className={mode === v ? "on" : ""} onClick={() => setMode(v)}>{t}</button>
        ))}</div>
      </div>
      <div className="opp-panel">
      <OpponentAvatar role={who(s.card)} mode={mode} avatarUrl={s.card.avatar_url ?? null} gender={s.card.voice ?? "female"}
        mood={s.mood ?? "neutral"} say={vs === undefined || intro ? null : say} ttsReady={!!vs?.tts} />
      <section className="bars">
        <Bar label="Доверие" value={(s.state.trust - t.breakdown_trust) / (10 - t.breakdown_trust)} hint="Растёт от вопросов об интересах и эмпатии, падает от давления" />
        <Bar label="Терпение" value={1 - s.state.irritation / t.breakdown_irritation} hint="Когда кончится, собеседник прервёт переговоры" />
        <Bar label="Готовность уступить" value={s.state.readiness / t.concede} hint="На 100% собеседник сдвигает позицию" />
        <p className="small muted">Позиция собеседника: {fmtValue(s.state.position, s.card.target_zone.unit)} · ход {s.turn}/{s.max_turns}</p>
      </section>
      </div>
      {intro
        ? <CoachPanel tips={tips} method={s.card.method} intro onDone={() => setIntro(false)} />
        : <div className="log">{s.messages.map((m, i) => (m.role === "user" && m.audio_url
          ? <VoiceMsg key={i} m={m} />
          : m.role === "user"
            ? <div key={i} className="msg user">{m.text}</div>
            : <div key={i} className="msg opp"><span className="msg-who">{name}</span>{m.text}</div>
        ))}</div>}
      {!intro && tipsOpen && <CoachPanel tips={tips} method={s.card.method} intro={false} onDone={() => setTipsOpen(false)} />}
      {!intro && !tipsOpen && tips.length > 0 && <CoachCorner hints={hints} method={s.card.method} onOpen={() => { setHints([]); setTipsOpen(true); }} onClose={() => setHints([])} />}
      {lastUser && <div className="small"><span className="muted">Ваш последний ход: </span><Chips labels={lastUser.labels} /></div>}
      {err && <p className="error">{err}</p>}
      <div className="row">
        <textarea value={msg} maxLength={2500} disabled={!ready} onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder={intro ? "Собеседник начнёт после наставлений" : "Ваша реплика"} />
        <button className="primary" disabled={!ready || !msg.trim()} onClick={send}>{busy ? "…" : "Отправить"}</button>
        <Recorder disabled={!ready} sttReady={!!vs?.stt} maxSeconds={vs?.max_seconds ?? 30} onSend={sendVoice} onError={setErr} />
      </div>
      <p className="small muted">{msg.length}/2500</p>
      <div className="row">
        <button disabled={!ready || s.turn === 0} onClick={undo}>Отменить последний ход</button>
        <button disabled={!ready} onClick={finish}>Завершить</button>
      </div>
    </main>
  );
}

function Result({ sid, go }: { sid: string; go: Go }) {
  const [r, setR] = useState<SessionResult | null>(null);
  const [s, setS] = useState<SessionView | null>(null);
  const [err, setErr] = useState("");
  const load = () => {
    setErr("");
    api.result(sid).then(setR).catch((e) => setErr(`Разбор не загрузился: ${e.message}`));
    api.session(sid).then(setS).catch(() => undefined);
  };
  useEffect(load, [sid]);
  const replay = async (turn: number) => {
    try { const v = await api.rewind(sid, turn); store.set(ACTIVE_KEY, v.id); go({ name: "dialog", sid: v.id }); } catch (e) { setErr(`Не удалось переиграть: ${(e as Error).message}`); }
  };
  if (err && !r) return <main><p className="error">{err}</p><div className="row"><button onClick={load}>Повторить</button><button onClick={() => go({ name: "list" })}>К сценариям</button></div></main>;
  if (!r) return <main><p>Судья разбирает диалог…</p></main>;
  const userTurns = s?.messages.filter((m) => m.role === "user") ?? [];
  return (
    <main className="result">
      <h2>{r.status === "active" ? "Сессия не завершена" : OUTCOME[r.outcome ?? ""] ?? r.outcome}</h2>
      {r.final_position !== null && <p>Итог: {s ? fmtValue(r.final_position, s.card.target_zone.unit) : r.final_position}{r.position_shift !== null && ` (сдвиг от вашей стартовой позиции: ${r.position_shift})`}</p>}
      {r.walk_away_note && <p className={r.walk_away_justified ? "" : "note"}>{r.walk_away_note}</p>}
      {r.incomplete && <p className="note">Меньше трёх реплик — полный разбор не строим.</p>}
      <p>Проговорено: {r.details_covered.join(", ") || "—"}</p>
      <p>Не проговорено: {r.details_missed.join(", ") || "—"}</p>
      {r.judge && (
        <>
          {r.judge_source === "rules" && <p className="note">Разбор по правилам (LLM недоступна)</p>}
          <h3>Оценки по осям</h3>
          <ul>{Object.entries(r.judge.axes).map(([k, v]) => <li key={k}>{k}: <b>{v}</b>/100</li>)}</ul>
          <h3>Ключевые моменты</h3>
          {r.judge.key_moments.map((m, i) => (
            <div key={i} className="moment"><q>{m.quote}</q><p>Что не так: {m.problem}</p><p>Лучше: {m.better}</p></div>
          ))}
          <p className="muted">Дальше: {r.judge.next_scenario_hint}</p>
        </>
      )}
      {userTurns.length > 0 && (
        <>
          <h3>Ваши ходы</h3>
          <ol className="turns">{userTurns.map((m, i) => (
            <li key={i}>
              <p>{m.text}</p>
              <Chips labels={m.labels} />
              <button onClick={() => replay(i)}>Переиграть отсюда</button>
            </li>
          ))}</ol>
        </>
      )}
      {err && <p className="error">{err}</p>}
      <div className="row">
        {r.status === "active" && <button className="primary" onClick={() => go({ name: "dialog", sid })}>Вернуться в диалог</button>}
        <button className={r.status === "active" ? "" : "primary"} onClick={() => go({ name: "list" })}>К сценариям</button>
      </div>
    </main>
  );
}

function History({ go }: { go: Go }) {
  const [items, setItems] = useState<Awaited<ReturnType<typeof api.history>>>([]);
  const [err, setErr] = useState("");
  useEffect(() => { api.history().then(setItems).catch((e) => setErr(`История не загрузилась: ${e.message}`)); }, []);
  return (
    <main>
      <h2>История сессий</h2>
      {err && <p className="error">{err}</p>}
      <ul className="history">{items.map((s) => (
        <li key={s.id} onClick={() => go(s.status === "active" ? { name: "dialog", sid: s.id } : { name: "result", sid: s.id })}>
          {s.scenario} — {s.status === "active" ? "в процессе" : OUTCOME[s.outcome ?? ""] ?? s.status} · ходов: {s.turns}
        </li>
      ))}</ul>
    </main>
  );
}

type Weak = "interests" | "criteria" | "emotions" | "offers" | "batna";
const WEAK_RU: Record<Weak, string> = { interests: "выяснение интересов", criteria: "объективные критерии", emotions: "контроль эмоций", offers: "уступки и обмен условиями", batna: "альтернатива и граница сделки" };
const WEAK_METHOD: Record<Weak, string> = { interests: "spin", criteria: "harvard", emotions: "harvard", offers: "batna", batna: "batna" };
// Все варианты звучат разумно: различаются техникой, а не вежливостью. 2 — лучший ход, 1 — частый ход с изъяном, 0 — ход, который ухудшает позицию.
// Порядок вариантов перемешивается при каждом прохождении.
const QUIZ: { q: string; a: [string, number, Weak | null][] }[] = [
  { q: "Руководитель: «Отчёт нужен к пятнице, клиент ждёт». Без данных соседнего отдела вы к пятнице не успеете. Первый ход?", a: [
    ["Предупреждаю, что к пятнице не успеваю, и предлагаю перенести на понедельник", 1, "interests"],
    ["Уточняю, какую часть клиент должен увидеть в пятницу, а что можно донести позже", 2, null],
    ["Беру срок и договариваюсь с соседним отделом, чтобы данные дали раньше", 0, "offers"],
    ["Прошу выделить мне помощника, чтобы успеть к пятнице", 1, "interests"],
  ] },
  { q: "Заказчик: «Конкурент делает то же самое на 20% дешевле». Ваш ответ?", a: [
    ["Спрашиваю, что именно входит в предложение конкурента и на каких условиях", 2, null],
    ["Объясняю, чем наше решение лучше, и сохраняю цену", 1, "interests"],
    ["Предлагаю скидку 10%, чтобы встретиться посередине", 0, "offers"],
    ["Предлагаю ту же цену при сокращённом объёме работ", 1, "interests"],
  ] },
  { q: "Коллега из соседнего отдела отказывается брать половину общей задачи: «У нас и так завал». Что делаете?", a: [
    ["Предлагаю поделить поровну: так будет честно для обоих отделов", 1, "criteria"],
    ["Выясняю, что у них горит сейчас, и предлагаю взять часть их работы в обмен", 2, null],
    ["Выношу вопрос на руководителя, пусть распределит", 0, "interests"],
    ["Беру задачу целиком: отношения с отделом важнее", 0, "offers"],
  ] },
  { q: "Собеседник резко: «Вы вообще понимаете, о чём говорите?» Ваша реакция?", a: [
    ["Спокойно уточняю, какой пункт вызвал сомнение", 2, null],
    ["Привожу три аргумента, почему моё предложение верное", 1, "emotions"],
    ["Говорю, что в таком тоне разговор не продолжу", 1, "emotions"],
    ["Извиняюсь и предлагаю пересмотреть условия", 0, "offers"],
  ] },
  { q: "Вы назвали 500 тыс. ₽ за проект, заказчик — 300 тыс. Как обоснуете свою цифру?", a: [
    ["Показываю расчёт: трудозатраты команды по этапам и рыночные ставки на такие работы", 2, null],
    ["Говорю, что это стандартная цена для проектов такого масштаба", 1, "criteria"],
    ["Сразу предлагаю 400 тыс., чтобы быстрее договориться", 0, "offers"],
    ["Ссылаюсь на то, что прошлый клиент заплатил столько же", 1, "criteria"],
  ] },
  { q: "Вы готовы уступить заказчику 5% цены. Как лучше это сделать?", a: [
    ["Уступаю сразу, чтобы показать добрую волю", 0, "offers"],
    ["Уступаю, если заказчик подписывает договор на год вместо квартала", 2, null],
    ["Беру паузу до завтра и возвращаюсь с уступкой", 1, "offers"],
    ["Предлагаю скидку при условии, что он согласится прямо сейчас", 1, "emotions"],
  ] },
  { q: "Поставщик поднимает цену на 10%. У вас есть другой поставщик с ростом 4%, но переход займёт месяц. Что делаете?", a: [
    ["Сразу говорю, что уйдём к другому, если цену не снизят", 0, "emotions"],
    ["Сравниваю его условия со своей альтернативой с учётом месяца на переход и называю, какой рост для нас приемлем", 2, null],
    ["Соглашаюсь на 10%: переход слишком рискованный", 0, "batna"],
    ["Прошу снизить рост до 4%, как у другого поставщика", 1, "batna"],
  ] },
  { q: "Третий ход подряд собеседник не двигается, а его условия уже хуже вашей альтернативы. Что делаете?", a: [
    ["Уступаю ещё, чтобы не потерять сделку", 0, "batna"],
    ["Спокойно завершаю переговоры и выбираю альтернативу", 2, null],
    ["Ставлю срок: решение нужно до конца дня", 1, "emotions"],
    ["Предлагаю перерыв и возвращаюсь с новым вариантом условий", 1, "batna"],
  ] },
];

function shuffled<T>(xs: T[]): T[] {
  const a = [...xs];
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

function EntryTest({ go }: { go: Go }) {
  const [answers, setAnswers] = useState<[string, number, Weak | null][]>([]);
  const [order, setOrder] = useState(() => QUIZ.map((x) => shuffled(x.a)));
  const [items, setItems] = useState<Scenario[]>([]);
  useEffect(() => { api.scenarios().then(setItems).catch(() => undefined); }, []);
  const skip = () => { store.set(TEST_KEY, "skipped"); go({ name: "list" }); };
  if (answers.length < QUIZ.length) {
    const { q } = QUIZ[answers.length];
    const a = order[answers.length];
    return (
      <main className="quiz">
        <p className="muted small">Входной тест · вопрос {answers.length + 1} из {QUIZ.length}. Подберём сложность и сценарий.</p>
        <h3>{q}</h3>
        {a.map((opt, i) => <button key={i} onClick={() => setAnswers([...answers, opt])}>{opt[0]}</button>)}
        <button className="link" onClick={skip}>Пропустить тест</button>
      </main>
    );
  }
  const picked = answers;
  const score = picked.reduce((sum, [, p]) => sum + p, 0);
  const level = score <= 7 ? "easy" : score <= 12 ? "medium" : "hard";
  const counts = picked.reduce((c, [, , w]) => (w ? { ...c, [w]: (c[w] ?? 0) + 1 } : c), {} as Partial<Record<Weak, number>>);
  const weak = (Object.keys(counts) as Weak[]).sort((x, y) => (counts[y] ?? 0) - (counts[x] ?? 0))[0];
  const rec = items.find((s) => s.difficulty === level && (!weak || s.method === WEAK_METHOD[weak])) ?? items.find((s) => s.difficulty === level) ?? items[0];
  store.set(TEST_KEY, JSON.stringify({ level, weak: weak ?? null }));
  return (
    <main className="quiz">
      <h2>Результат теста</h2>
      <p>Рекомендуемая сложность: <b>{RU[level]}</b>.</p>
      <p>{weak ? <>Слабее всего: <b>{WEAK_RU[weak]}</b>.</> : "Явно слабых сторон тест не показал."}</p>
      {rec && <p>Начните со сценария «{rec.name}» ({RU[rec.difficulty]}, метод {RU[rec.method]}).</p>}
      <div className="row">
        {rec && <button className="primary" onClick={() => startScenario(rec.id, go, () => go({ name: "list" }))}>Начать</button>}
        <button onClick={() => go({ name: "list" })}>К сценариям</button>
        <button onClick={() => { setAnswers([]); setOrder(QUIZ.map((x) => shuffled(x.a))); }}>Пройти заново</button>
      </div>
    </main>
  );
}
