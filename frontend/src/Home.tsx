import { useEffect, useState } from "react";
import { api, editKeys, HistoryItem, Scenario, SessionView, store, User } from "./api";
import { Art, ART, Empty, GroupArt, Scene } from "./art";
import { MASCOT } from "./Coach";
import { Icon } from "./icons";
import { ACTIVE_KEY, dayLabel, Go, METHOD_ICON, OUTCOME, outcomeTone, parseAt, plural, recommend, RU, startScenario, STYLE_RU, testResult, WEAK_RU } from "./shared";

function Diff({ level }: { level: Scenario["difficulty"] }) {
  const n = level === "easy" ? 1 : level === "medium" ? 2 : 3;
  return <span className="diff" aria-hidden="true">{[0, 1, 2].map((i) => <i key={i} className={i < n ? "on" : ""} />)}</span>;
}

export function SessionRow({ h, go }: { h: HistoryItem; go: Go }) {
  const active = h.status === "active";
  const tone = active ? "accent" : outcomeTone(h.outcome);
  return (
    <div className="rrow" role="button" tabIndex={0} onClick={() => go(active ? { name: "dialog", sid: h.id } : { name: "result", sid: h.id })}
      onKeyDown={(e) => { if (e.key === "Enter") go(active ? { name: "dialog", sid: h.id } : { name: "result", sid: h.id }); }}>
      <b>{h.scenario}</b>
      <span className="num">{h.score != null ? Math.round(h.score) : "—"}</span>
      <span className="o"><span className={`dot ${tone}`} />{active ? `Не завершён, ход ${h.turns}` : OUTCOME[h.outcome ?? ""] ?? h.status}</span>
      <span className="d">{dayLabel(parseAt(h.created_at))}</span>
    </div>
  );
}

export default function Home({ user, go }: { user: User | null; go: Go }) {
  const [items, setItems] = useState<Scenario[]>([]);
  const [active, setActive] = useState<SessionView | null>(null);
  const [hist, setHist] = useState<HistoryItem[]>([]);
  const [err, setErr] = useState("");
  const keys = editKeys.all();
  const canEdit = (s: Scenario) => s.can_edit || !!keys[s.id];
  useEffect(() => {
    api.scenarios().then(setItems).catch((e) => setErr(`Сценарии не загрузились: ${e.message}`));
    api.history().then(setHist).catch(() => undefined);
    const sid = store.get(ACTIVE_KEY);
    if (sid) api.session(sid).then((s) => (s.status === "active" ? setActive(s) : store.set(ACTIVE_KEY, null))).catch(() => store.set(ACTIVE_KEY, null));
  }, []);
  const test = testResult();
  const rec = test && items.length ? recommend(items, test.level, test.weak) : undefined;
  const passed = (id: string) => hist.filter((h) => h.scenario_id === id && h.status === "finished" && h.outcome !== "user_finished");
  const passedCount = items.filter((s) => passed(s.id).length).length;
  const groups: [string, Scenario[]][] = [];
  items.forEach((s) => { const g = groups.find(([d]) => d === s.domain); if (g) g[1].push(s); else groups.push([s.domain, [s]]); });
  const first = (g: Scenario[]) => g.some((s) => s.id === active?.scenario_id || s.id === rec?.id);
  groups.sort((a, b) => Number(first(b[1])) - Number(first(a[1])));
  const lastOpp = active ? [...active.messages].reverse().find((m) => m.role === "opponent") : undefined;
  const lastAt = active ? parseAt(active.messages[active.messages.length - 1]?.at) : null;
  const segs = (n: number, of: number) => <span className="segs">{Array.from({ length: Math.min(of, 20) }, (_, i) => <i key={i} className={i < n ? "on" : ""} />)}</span>;

  return (
    <main className="flush">
      <Scene art={ART.hero} size="wide" className="hero">
          {active ? <>
            <span className="caps">Незавершённая сессия{lastAt && ` · ${dayLabel(lastAt)}`}</span>
            <h1>{active.card.name}</h1>
            {lastOpp && <p className="last">Последняя реплика собеседника: <q>{lastOpp.text}</q></p>}
            <div className="prog">{segs(active.turn, active.max_turns)}<span className="num">ход {active.turn} из {active.max_turns}</span></div>
            <div className="acts">
              <button className="primary" onClick={() => go({ name: "dialog", sid: active.id })}>Продолжить<Icon name="arrow" size={16} /></button>
              <button className="ghost" onClick={() => { store.set(ACTIVE_KEY, null); setActive(null); }}>Скрыть</button>
            </div>
          </> : <>
            <span className="caps">Тренажёр переговоров</span>
            <h1>Выберите сценарий и договоритесь</h1>
            <p className="last">Собеседник отвечает по правилам метода и помнит ваши ходы. После диалога — разбор: что сработало, где уступили и как сказать лучше.</p>
            <div className="acts">
              {rec
                ? <button className="primary" onClick={() => startScenario(rec.id, go, setErr)}>Начать «{rec.name}»<Icon name="arrow" size={16} /></button>
                : <button className="primary" onClick={() => go({ name: "test" })}>Пройти входной тест<Icon name="arrow" size={16} /></button>}
            </div>
          </>}
      </Scene>

      <div className="home">
        <div>
          <div className="lh">
            <div className="lt"><Art className="mag" src={ART.magnet} /><div><h2>Сценарии</h2><div className="cap">{items.length} {plural(items.length, "сценарий", "сценария", "сценариев")}{passedCount > 0 && ` · ${passedCount} пройдено`}</div></div></div>
            <button onClick={() => go({ name: "setup" })}><Icon name="plus" size={16} />Новый сценарий</button>
          </div>
          {err && <p className="error">{err}</p>}
          {groups.map(([domain, list]) => (
            <section key={domain} className="group">
              <div className="gh"><GroupArt domain={domain} icon={list[0].domain_icon} /><b>{domain || "Без сферы"}</b><span className="cap">{list.length} {plural(list.length, "сценарий", "сценария", "сценариев")}</span></div>
              {list.map((s) => {
                const cont = active?.scenario_id === s.id ? active : null;
                const done = passed(s.id);
                const best = Math.max(...done.map((h) => h.score ?? -1));
                return (
                  <article key={s.id} className={`item ${rec?.id === s.id ? "rec" : ""}`}>
                    <div>
                      <div className="nm">
                        <b>{s.name}</b>
                        {cont ? <span className="st cont">Не завершён · ход {cont.turn} из {cont.max_turns}</span>
                          : done.length > 0 && <span className="st"><Icon name="check" size={13} />Пройден{best >= 0 && ` · лучший ${Math.round(best)}`}</span>}
                        {rec?.id === s.id && <span className="flag">Рекомендуем по входному тесту</span>}
                        {s.locked_by_org && <span className="flag org"><Icon name="lock" size={13} />Зафиксирован организацией</span>}
                      </div>
                      <p className="topic">{s.topic}</p>
                      <div className="meta">
                        <span><Icon name={METHOD_ICON[s.method] ?? "chat"} size={14} />{RU[s.method]}</span>
                        <span><Diff level={s.difficulty} />{RU[s.difficulty]}</span>
                        <span><Icon name="turns" size={14} />{s.max_turns} {plural(s.max_turns, "ход", "хода", "ходов")}</span>
                        <span>собеседник {STYLE_RU[s.style] ?? RU[s.style]}</span>
                      </div>
                    </div>
                    <div className="go">
                      {canEdit(s)
                        ? <button className="icon" title="Настроить" aria-label={`Настроить «${s.name}»`} onClick={() => go({ name: "setup", scenario: s })}><Icon name="edit" size={16} /></button>
                        : <button className="icon" title={s.builtin ? "Сделать копию: встроенный сценарий не меняется" : "Сделать копию: сценарий чужой"} aria-label={`Сделать копию «${s.name}»`}
                          onClick={() => go({ name: "setup", scenario: s, copy: true })}><Icon name="copy" size={16} /></button>}
                      {cont
                        ? <button className="primary" onClick={() => go({ name: "dialog", sid: cont.id })}>Продолжить</button>
                        : <button className={rec?.id === s.id ? "primary" : ""} onClick={() => startScenario(s.id, go, setErr)}>Начать</button>}
                    </div>
                  </article>
                );
              })}
            </section>
          ))}
        </div>
        <div className="aside">
          <div className="card testcard">
            <span className="caps">Входной тест · 8 вопросов</span>
            {test
              ? <p>Рекомендуемая сложность: <b>{RU[test.level]}</b>.{test.weak && <> Слабее всего: <b>{WEAK_RU[test.weak]}</b>.</>}</p>
              : <p>Восемь рабочих ситуаций. По ответам подберём сложность и первый сценарий.</p>}
            <button className="link" onClick={() => go({ name: "test" })}>{test ? "Пройти заново" : "Пройти тест"}</button>
            <img src={MASCOT} alt="" />
          </div>
          {hist.length > 0
            ? (
              <div className="card recent">
                <h3>{user ? "Последние сессии" : "Ваши последние сессии"}</h3>
                {hist.slice(0, 5).map((h) => <SessionRow key={h.id} h={h} go={go} />)}
                <div className="rfoot">
                  <button className="link" onClick={() => go({ name: "history" })}>Вся история</button>
                  <Art className="folders" src={ART.folders} />
                </div>
              </div>
            )
            : <div className="recent"><Empty art={ART.coffee} title="Сессий пока нет"><p>Начните любой сценарий: здесь появятся последние сессии и ссылки на разборы.</p></Empty></div>}
        </div>
      </div>
    </main>
  );
}
