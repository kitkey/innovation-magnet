import { useEffect, useState } from "react";
import { api, Scenario, ScenarioCard, SessionResult, TurnOut } from "./api";

type View = { name: "list" } | { name: "setup"; scenario?: Scenario } | { name: "dialog"; scenario: Scenario } | { name: "result"; sid: string } | { name: "history" };

const OUTCOME: Record<string, string> = {
  agreement_in_zone: "Соглашение в целевой зоне",
  agreement_out_of_zone: "Соглашение вне целевой зоны",
  breakdown: "Срыв переговоров",
  turn_limit: "Лимит ходов",
  user_finished: "Завершено пользователем",
};

const RU: Record<string, string> = { easy: "лёгкая", medium: "средняя", hard: "сложная", spin: "SPIN", harvard: "Гарвардский", free: "свободный", cooperative: "сотрудничающий", avoiding: "уклоняющийся", pressing: "давящий", emotional: "эмоциональный" };
const STYLE_RU: Record<string, string> = { hard: "жёсткий" };

const EMPTY: ScenarioCard = {
  name: "", domain: "", topic: "", difficulty: "medium", tone: "neutral", method: "free", style: "hard",
  user_role: "", user_goal: "", opponent_role: "", opponent_goal: "", opponent_hidden_interests: [],
  opponent_batna: "", user_batna: "", target_zone: { unit: "", user_start: 0, zone_min: 0, zone_max: 0, opponent_start: 0 },
  mandatory_details: [], context: "", max_turns: 10, locked_by_org: false,
};

export default function App() {
  const [view, setView] = useState<View>({ name: "list" });
  return (
    <div className="app">
      <header>
        <b onClick={() => setView({ name: "list" })}>Арена переговоров</b>
        <nav>
          <button onClick={() => setView({ name: "list" })}>Сценарии</button>
          <button onClick={() => setView({ name: "setup" })}>Новый сценарий</button>
          <button onClick={() => setView({ name: "history" })}>История</button>
        </nav>
      </header>
      {view.name === "list" && <List go={setView} />}
      {view.name === "setup" && <Setup scenario={view.scenario} go={setView} />}
      {view.name === "dialog" && <Dialog scenario={view.scenario} go={setView} />}
      {view.name === "result" && <Result sid={view.sid} go={setView} />}
      {view.name === "history" && <History go={setView} />}
    </div>
  );
}

function List({ go }: { go: (v: View) => void }) {
  const [items, setItems] = useState<Scenario[]>([]);
  useEffect(() => { api.scenarios().then(setItems); }, []);
  return (
    <main className="cards">
      {items.map((s) => (
        <article key={s.id} className="card">
          <h3>{s.name}</h3>
          <p className="muted">{s.domain} · {RU[s.difficulty]} · метод: {RU[s.method]} · стиль: {STYLE_RU[s.style] ?? RU[s.style]}</p>
          <p>{s.topic}</p>
          <div className="row">
            <button className="primary" onClick={() => go({ name: "dialog", scenario: s })}>Начать</button>
            {!s.locked_by_org && <button onClick={() => go({ name: "setup", scenario: s })}>Настроить</button>}
          </div>
        </article>
      ))}
    </main>
  );
}

function lines(v: string) { return v.split("\n").map((x) => x.trim()).filter(Boolean); }

function Setup({ scenario, go }: { scenario?: Scenario; go: (v: View) => void }) {
  const [card, setCard] = useState<ScenarioCard>(scenario ?? EMPTY);
  const [brief, setBrief] = useState("");
  const [err, setErr] = useState("");
  const set = (k: keyof ScenarioCard, v: unknown) => setCard({ ...card, [k]: v });
  const setZone = (k: string, v: string) => setCard({ ...card, target_zone: { ...card.target_zone, [k]: k === "unit" ? v : Number(v) } });
  const save = async () => {
    try {
      const s = scenario ? await api.updateScenario(scenario.id, card) : await api.createScenario(card);
      go({ name: "dialog", scenario: s });
    } catch (e) { setErr(String(e)); }
  };
  const gen = async () => { try { setCard(await api.generate(brief)); } catch (e) { setErr(String(e)); } };
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
      </fieldset>
      <label>Обязательные детали (по строке)<textarea value={card.mandatory_details.join("\n")} onChange={(e) => set("mandatory_details", lines(e.target.value))} /></label>
      {text("context", "Контекст", true)}
      <label>Лимит ходов<input type="number" value={card.max_turns} onChange={(e) => set("max_turns", Number(e.target.value))} /></label>
      <label className="check"><input type="checkbox" checked={card.locked_by_org} onChange={(e) => set("locked_by_org", e.target.checked)} />Зафиксировать для сотрудников организации</label>
      {err && <p className="error">{err}</p>}
      <button className="primary" onClick={save}>Сохранить и начать</button>
    </main>
  );
}

function Dialog({ scenario, go }: { scenario: Scenario; go: (v: View) => void }) {
  const [sid, setSid] = useState("");
  const [log, setLog] = useState<{ who: "user" | "opp"; text: string }[]>([]);
  const [msg, setMsg] = useState("");
  const [last, setLast] = useState<TurnOut | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.start(scenario.id).then((r) => { setSid(r.session_id); setLog([{ who: "opp", text: r.opening }]); }); }, [scenario.id]);
  const send = async () => {
    if (!msg.trim() || busy) return;
    setBusy(true);
    setLog((l) => [...l, { who: "user", text: msg }]);
    const r = await api.turn(sid, msg);
    setMsg(""); setBusy(false); setLast(r);
    setLog((l) => [...l, { who: "opp", text: r.opponent_message }]);
    if (r.status === "finished") go({ name: "result", sid });
  };
  const finish = async () => { await api.finish(sid); go({ name: "result", sid }); };
  return (
    <main className="dialog">
      <p className="muted">{scenario.user_role} ↔ {scenario.opponent_role}. Цель: {scenario.user_goal}</p>
      <div className="log">{log.map((m, i) => <div key={i} className={`msg ${m.who}`}>{m.text}</div>)}</div>
      {last && <p className="muted small">Ход {last.turn}/{scenario.max_turns}</p>}
      <div className="row">
        <textarea value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder="Ваша реплика" />
        <button className="primary" disabled={busy} onClick={send}>Отправить</button>
      </div>
      <button onClick={finish}>Завершить</button>
    </main>
  );
}

function Result({ sid, go }: { sid: string; go: (v: View) => void }) {
  const [r, setR] = useState<SessionResult | null>(null);
  useEffect(() => { api.result(sid).then(setR); }, [sid]);
  if (!r) return <main><p>Судья разбирает диалог…</p></main>;
  if (r.incomplete) return <main><h2>Сессия неполная</h2><p>Меньше трёх реплик — разбор не строим.</p><button onClick={() => go({ name: "list" })}>К сценариям</button></main>;
  return (
    <main className="result">
      <h2>{OUTCOME[r.outcome ?? ""] ?? r.outcome}</h2>
      {r.final_position !== null && <p>Итог: {r.final_position}{r.position_shift !== null && ` (сдвиг от вашей стартовой позиции: ${r.position_shift})`}</p>}
      <p>Проговорено: {r.details_covered.join(", ") || "—"}</p>
      <p>Не проговорено: {r.details_missed.join(", ") || "—"}</p>
      {r.judge && (
        <>
          <h3>Оценки по осям</h3>
          <ul>{Object.entries(r.judge.axes).map(([k, v]) => <li key={k}>{k}: <b>{v}</b>/100</li>)}</ul>
          <h3>Ключевые моменты</h3>
          {r.judge.key_moments.map((m, i) => (
            <div key={i} className="moment"><q>{m.quote}</q><p>Что не так: {m.problem}</p><p>Лучше: {m.better}</p></div>
          ))}
          <p className="muted">Дальше: {r.judge.next_scenario_hint}</p>
        </>
      )}
      <button className="primary" onClick={() => go({ name: "list" })}>К сценариям</button>
    </main>
  );
}

function History({ go }: { go: (v: View) => void }) {
  const [items, setItems] = useState<Awaited<ReturnType<typeof api.history>>>([]);
  useEffect(() => { api.history().then(setItems); }, []);
  return (
    <main>
      <h2>История сессий</h2>
      <ul className="history">{items.map((s) => (
        <li key={s.id} onClick={() => go({ name: "result", sid: s.id })}>{s.scenario} — {OUTCOME[s.outcome ?? ""] ?? s.status} · ходов: {s.turns}</li>
      ))}</ul>
    </main>
  );
}
