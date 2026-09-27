import { useEffect, useState } from "react";
import { api, Scenario, ScenarioCard, SessionResult, SessionView, store } from "./api";

type View = { name: "list" } | { name: "setup"; scenario?: Scenario } | { name: "dialog"; sid: string } | { name: "result"; sid: string } | { name: "history" } | { name: "test" };
type Go = (v: View) => void;

const OUTCOME: Record<string, string> = {
  agreement_in_zone: "Соглашение в целевой зоне",
  agreement_out_of_zone: "Соглашение вне целевой зоны",
  breakdown: "Срыв переговоров",
  turn_limit: "Лимит ходов",
  user_finished: "Завершено пользователем",
};

const RU: Record<string, string> = { easy: "лёгкая", medium: "средняя", hard: "сложная", spin: "SPIN", harvard: "Гарвардский", free: "свободный", cooperative: "сотрудничающий", avoiding: "уклоняющийся", pressing: "давящий", emotional: "эмоциональный" };
const STYLE_RU: Record<string, string> = { hard: "жёсткий" };

const LABEL_RU: Record<string, string> = {
  interest_question: "вопрос об интересах", spin_situation: "ситуационный вопрос", spin_problem: "проблемный вопрос",
  spin_implication: "извлекающий вопрос", spin_need_payoff: "направляющий вопрос", objective_criterion: "объективный критерий",
  option_generation: "варианты", concrete_offer: "конкретное предложение", concession: "уступка", empathy: "эмпатия",
  argument: "аргумент", mandatory_detail: "обязательная деталь", pressure: "давление", personal_attack: "переход на личности",
  vague: "общая фраза", accept: "согласие", manipulation: "манипуляция",
};
const BAD_LABELS = new Set(["pressure", "personal_attack", "vague", "manipulation"]);

const ACTIVE_KEY = "arena.activeSid";
const TEST_KEY = "arena.test";

const EMPTY: ScenarioCard = {
  name: "", domain: "", topic: "", difficulty: "medium", tone: "neutral", method: "free", style: "hard",
  user_role: "", user_goal: "", opponent_role: "", opponent_goal: "", opponent_hidden_interests: [],
  opponent_batna: "", user_batna: "", target_zone: { unit: "", user_start: 0, zone_min: 0, zone_max: 0, opponent_start: 0 },
  mandatory_details: [], context: "", max_turns: 10, locked_by_org: false,
};

export default function App() {
  const [view, setView] = useState<View>(() => (store.get(TEST_KEY) ? { name: "list" } : { name: "test" }));
  return (
    <div className="app">
      <header>
        <b onClick={() => setView({ name: "list" })}>Арена переговоров</b>
        <nav>
          <button onClick={() => setView({ name: "list" })}>Сценарии</button>
          <button onClick={() => setView({ name: "setup" })}>Новый сценарий</button>
          <button onClick={() => setView({ name: "history" })}>История</button>
          <button onClick={() => setView({ name: "test" })}>Входной тест</button>
        </nav>
      </header>
      {view.name === "list" && <List go={setView} />}
      {view.name === "setup" && <Setup scenario={view.scenario} go={setView} />}
      {view.name === "dialog" && <Dialog key={view.sid} sid={view.sid} go={setView} />}
      {view.name === "result" && <Result key={view.sid} sid={view.sid} go={setView} />}
      {view.name === "history" && <History go={setView} />}
      {view.name === "test" && <EntryTest go={setView} />}
    </div>
  );
}

async function startScenario(id: string, go: Go, setErr: (e: string) => void) {
  try { go({ name: "dialog", sid: (await api.start(id)).session_id }); } catch (e) { setErr(`Не удалось начать сессию: ${(e as Error).message}`); }
}

function List({ go }: { go: Go }) {
  const [items, setItems] = useState<Scenario[]>([]);
  const [active, setActive] = useState<SessionView | null>(null);
  const [err, setErr] = useState("");
  const admin = !!store.get("arena.adminToken");
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
            {(!s.locked_by_org || admin) && <button onClick={() => go({ name: "setup", scenario: s })}>Настроить</button>}
          </div>
        </article>
      ))}
    </main>
  );
}

function lines(v: string) { return v.split("\n").map((x) => x.trim()).filter(Boolean); }

function Setup({ scenario, go }: { scenario?: Scenario; go: Go }) {
  const [card, setCard] = useState<ScenarioCard>(scenario ?? EMPTY);
  const [brief, setBrief] = useState("");
  const [err, setErr] = useState("");
  const [token, setToken] = useState(store.get("arena.adminToken") ?? "");
  const set = (k: keyof ScenarioCard, v: unknown) => setCard({ ...card, [k]: v });
  const setZone = (k: string, v: string) => setCard({ ...card, target_zone: { ...card.target_zone, [k]: k === "unit" ? v : Number(v) } });
  const saveToken = (v: string) => { setToken(v); store.set("arena.adminToken", v.trim() || null); };
  const save = async () => {
    setErr("");
    try {
      const s = scenario ? await api.updateScenario(scenario.id, card) : await api.createScenario(card);
      await startScenario(s.id, go, setErr);
    } catch (e) { setErr((e as Error).message); }
  };
  const gen = async () => { setErr(""); try { setCard(await api.generate(brief)); } catch (e) { setErr((e as Error).message); } };
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
      {select("method", "Метод, который тренируем", [["free", "Свободный"], ["spin", "SPIN"], ["harvard", "Гарвардский"]])}
      {select("style", "Стиль собеседника", [["hard", "Жёсткий"], ["cooperative", "Сотрудничающий"], ["avoiding", "Уклоняющийся"], ["pressing", "Давящий"], ["emotional", "Эмоциональный"]])}
      {text("user_role", "Ваша роль")}{text("user_goal", "Ваша цель", true)}
      {text("opponent_role", "Роль собеседника")}{text("opponent_goal", "Цель собеседника", true)}
      <label>Скрытые интересы собеседника (по строке)<textarea value={card.opponent_hidden_interests.join("\n")} onChange={(e) => set("opponent_hidden_interests", lines(e.target.value))} /></label>
      {text("opponent_batna", "BATNA собеседника")}{text("user_batna", "Ваша BATNA")}
      <fieldset><legend>Целевая зона соглашения</legend>
        <label>Единица<input value={card.target_zone.unit} onChange={(e) => setZone("unit", e.target.value)} /></label>
        <label>Ваша стартовая позиция<input type="number" value={card.target_zone.user_start} onChange={(e) => setZone("user_start", e.target.value)} /></label>
        <label>Зона от<input type="number" value={card.target_zone.zone_min} onChange={(e) => setZone("zone_min", e.target.value)} /></label>
        <label>Зона до<input type="number" value={card.target_zone.zone_max} onChange={(e) => setZone("zone_max", e.target.value)} /></label>
        <label>Старт собеседника<input type="number" value={card.target_zone.opponent_start} onChange={(e) => setZone("opponent_start", e.target.value)} /></label>
        <p className="muted small">Зона лежит между стартовыми позициями сторон.</p>
      </fieldset>
      <label>Обязательные детали (по строке)<textarea value={card.mandatory_details.join("\n")} onChange={(e) => set("mandatory_details", lines(e.target.value))} /></label>
      {text("context", "Контекст", true)}
      <label>Лимит ходов<input type="number" value={card.max_turns} onChange={(e) => set("max_turns", Number(e.target.value))} /></label>
      <label className="check"><input type="checkbox" checked={card.locked_by_org} onChange={(e) => set("locked_by_org", e.target.checked)} />Зафиксировать для сотрудников организации</label>
      <label>Токен администратора (нужен, чтобы фиксировать сценарии и менять зафиксированные)<input type="password" value={token} onChange={(e) => saveToken(e.target.value)} /></label>
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

function Dialog({ sid, go }: { sid: string; go: Go }) {
  const [s, setS] = useState<SessionView | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const load = () => api.session(sid).then((v) => {
    if (v.status !== "active") { store.set(ACTIVE_KEY, null); go({ name: "result", sid }); return; }
    store.set(ACTIVE_KEY, sid); setS(v);
  }).catch((e) => setErr(`Сессия не загрузилась: ${e.message}`));
  useEffect(() => { load(); }, [sid]);

  const send = async () => {
    if (!s || !msg.trim() || busy) return;
    const text = msg;
    setBusy(true); setErr("");
    setS({ ...s, messages: [...s.messages, { role: "user", text, labels: [] }] });
    try {
      const r = await api.turn(sid, text);
      setMsg("");
      setS({
        ...s, turn: r.turn, status: r.status, outcome: r.outcome, state: r.state,
        messages: [...s.messages, { role: "user", text, labels: r.analysis.labels }, { role: "opponent", text: r.opponent_message, labels: [] }],
      });
      if (r.status === "finished") { store.set(ACTIVE_KEY, null); go({ name: "result", sid }); }
    } catch (e) {
      setS(s);
      setErr(`Ход не отправлен: ${(e as Error).message}. Попробуйте ещё раз.`);
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
  const ready = !busy && s.status === "active";
  return (
    <main className="dialog">
      <p className="muted">{s.card.user_role} ↔ {s.card.opponent_role}. Цель: {s.card.user_goal}</p>
      <section className="bars">
        <Bar label="Доверие" value={(s.state.trust - t.breakdown_trust) / (10 - t.breakdown_trust)} hint="Растёт от вопросов об интересах и эмпатии, падает от давления" />
        <Bar label="Терпение" value={1 - s.state.irritation / t.breakdown_irritation} hint="Когда кончится, собеседник прервёт переговоры" />
        <Bar label="Готовность уступить" value={s.state.readiness / t.concede} hint="На 100% собеседник сдвигает позицию" />
        <p className="small muted">Позиция собеседника: {s.state.position} {s.card.target_zone.unit} · ход {s.turn}/{s.max_turns}</p>
      </section>
      <div className="log">{s.messages.map((m, i) => (
        <div key={i} className={`msg ${m.role === "user" ? "user" : "opp"}`}>{m.text}</div>
      ))}</div>
      {lastUser && <div className="small"><span className="muted">Ваш последний ход: </span><Chips labels={lastUser.labels} /></div>}
      {err && <p className="error">{err}</p>}
      <div className="row">
        <textarea value={msg} maxLength={2500} disabled={!ready} onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder="Ваша реплика" />
        <button className="primary" disabled={!ready || !msg.trim()} onClick={send}>{busy ? "…" : "Отправить"}</button>
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
      {r.final_position !== null && <p>Итог: {r.final_position} {s?.card.target_zone.unit}{r.position_shift !== null && ` (сдвиг от вашей стартовой позиции: ${r.position_shift})`}</p>}
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

type Weak = "interests" | "criteria" | "emotions" | "offers";
const WEAK_RU: Record<Weak, string> = { interests: "выяснение интересов", criteria: "объективные критерии", emotions: "контроль эмоций", offers: "конкретные предложения и уступки" };
const WEAK_METHOD: Record<Weak, string> = { interests: "spin", criteria: "harvard", emotions: "harvard", offers: "spin" };
const QUIZ: { q: string; a: [string, number, Weak | null][] }[] = [
  { q: "Руководитель говорит: «Отчёт нужен завтра, и точка». Ваш первый ход?", a: [
    ["Соглашаюсь, спорить бесполезно", 0, "interests"],
    ["Спрашиваю, что именно нужно к завтра и зачем", 2, null],
    ["Говорю, что это нереально, пусть ищет другого", 0, "emotions"],
    ["Сразу называю свой срок — через неделю", 1, "interests"],
  ] },
  { q: "Заказчик просит скидку 20%. Что делаете?", a: [
    ["Даю скидку, чтобы не потерять клиента", 0, "offers"],
    ["Спрашиваю, чем вызвана просьба, и предлагаю уменьшить объём", 2, null],
    ["Отказываю без объяснений", 0, "emotions"],
    ["Предлагаю 10% без условий", 1, "offers"],
  ] },
  { q: "Собеседник повышает голос. Ваша реакция?", a: [
    ["Отвечаю тем же", 0, "emotions"],
    ["Признаю его беспокойство и возвращаю разговор к сути", 2, null],
    ["Замолкаю и соглашаюсь", 0, "interests"],
    ["Предлагаю продолжить позже", 1, "emotions"],
  ] },
  { q: "Как вы обосновываете свою цифру?", a: [
    ["Говорю, что мне так нужно", 0, "criteria"],
    ["Ссылаюсь на рынок, расчёт или норматив", 2, null],
    ["Не обосновываю, жду реакцию", 0, "criteria"],
    ["Ссылаюсь на опыт коллег", 1, "criteria"],
  ] },
];

function EntryTest({ go }: { go: Go }) {
  const [answers, setAnswers] = useState<number[]>([]);
  const [items, setItems] = useState<Scenario[]>([]);
  useEffect(() => { api.scenarios().then(setItems).catch(() => undefined); }, []);
  const skip = () => { store.set(TEST_KEY, "skipped"); go({ name: "list" }); };
  if (answers.length < QUIZ.length) {
    const { q, a } = QUIZ[answers.length];
    return (
      <main className="quiz">
        <p className="muted small">Входной тест · вопрос {answers.length + 1} из {QUIZ.length}. Подберём сложность и сценарий.</p>
        <h3>{q}</h3>
        {a.map(([text], i) => <button key={i} onClick={() => setAnswers([...answers, i])}>{text}</button>)}
        <button className="link" onClick={skip}>Пропустить тест</button>
      </main>
    );
  }
  const picked = answers.map((i, n) => QUIZ[n].a[i]);
  const score = picked.reduce((sum, [, p]) => sum + p, 0);
  const level = score <= 3 ? "easy" : score <= 6 ? "medium" : "hard";
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
        <button onClick={() => setAnswers([])}>Пройти заново</button>
      </div>
    </main>
  );
}
