import { useEffect, useState } from "react";
import { api, fmtValue, isOrdinal, optIndex, SessionResult, SessionView, store, TargetZone, zoneSubject } from "./api";
import { ART, Scene } from "./art";
import { Icon } from "./icons";
import { ACTIVE_KEY, cap, dayLabel, Go, hhmm, Marks, meters, OUTCOME, outcomeTone, parseAt, sessionScore, startScenario, turnStates } from "./shared";

const AXIS_WHY: Record<string, string> = {
  "ситуационные вопросы": "Вопросы о фактах и текущем положении собеседника",
  "проблемные вопросы": "Вопросы о трудностях и недовольстве собеседника",
  "извлекающие вопросы": "Вопросы о последствиях проблемы",
  "направляющие вопросы": "Вопросы о пользе решения для собеседника",
  "люди отдельно от проблемы": "Спокойный тон, без давления и оценок человека",
  "интересы, а не позиции": "Выяснили, зачем собеседнику его условие",
  "варианты взаимной выгоды": "Предложили варианты, выгодные обеим сторонам",
  "объективные критерии": "Опирались на рынок, регламент или расчёт",
  "сравнение с альтернативой": "Сравнивали предложение со своей альтернативой",
  "защита границы": "Не уступили дальше своей границы",
  "обмен условиями": "Уступали только в обмен на встречное условие",
  "исследование интересов": "Выяснили, что важно собеседнику",
  "выяснение интересов": "Выяснили, что важно собеседнику",
  "аргументация": "Обосновали свою позицию доводами",
  "конкретные предложения": "Назвали конкретные цифры и условия",
  "контроль эмоций": "Сохраняли спокойный тон под давлением",
};

/** Сценка исхода: рукопожатие только там, где договорились. */
function outcomeArt(outcome: string | null): string {
  if (outcome === "agreement_in_zone" || outcome === "agreement_out_of_zone") return ART.agree;
  if (outcome === "breakdown") return ART.breakdown;
  if (outcome === "walk_away") return ART.walkaway;
  return ART.hero;
}

const norm = (t: string) => t.toLowerCase().replace(/ё/g, "е").replace(/[^\p{L}\p{N}\s]/gu, " ").replace(/\s+/g, " ").trim();

/** Доверие и готовность уступить по ходам, 0–100. Отметка — ход первого ключевого момента. */
function Spark({ trust, ready, mark }: { trust: number[]; ready: number[]; mark: number | null }) {
  const W = 340, H = 150, L = 28, R = 12, T = 12, B = 22;
  const n = Math.max(trust.length - 1, 1);
  const x = (i: number) => L + (i / n) * (W - L - R);
  const y = (v: number) => T + (1 - v / 100) * (H - T - B);
  const path = (vs: number[]) => vs.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const series: [number[], string, string, string | undefined][] = [[trust, "var(--accent)", "Доверие", undefined], [ready, "#3AA8E0", "Готовность уступить", "5 3"]];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Доверие: ${trust.join(", ")}. Готовность уступить: ${ready.join(", ")}.`}>
      {[0, 50, 100].map((v) => <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line-2)" /><text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="#59617D">{v}</text></g>)}
      {trust.map((_, i) => <text key={i} x={x(i)} y={H - 5} textAnchor="middle" fontSize="11" fill="#59617D">{i}</text>)}
      {mark !== null && mark <= n && <g><line x1={x(mark)} x2={x(mark)} y1={T} y2={H - B} stroke="var(--bad)" strokeDasharray="3 3" /><text x={x(mark) + 4} y={T + 9} fontSize="11" fill="var(--bad)">ход {mark}</text></g>}
      {series.map(([vs, c, name, dash]) => (
        <g key={name}>
          <path d={path(vs)} fill="none" stroke={c} strokeWidth="2" strokeDasharray={dash} strokeLinejoin="round" strokeLinecap="round" />
          {vs.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r="3" fill="var(--surface)" stroke={c} strokeWidth="1.6"><title>{`${name}, ход ${i}: ${v}%`}</title></circle>)}
        </g>
      ))}
    </svg>
  );
}

export default function Result({ sid, go }: { sid: string; go: Go }) {
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
  if (!r) return <main><p className="muted">Судья разбирает диалог…</p></main>;

  const card = s?.card;
  const users = s?.messages.filter((m) => m.role === "user") ?? [];
  const states = s ? turnStates(s) : [];
  const tone = outcomeTone(r.outcome, r.walk_away_justified);
  const title = r.status === "active" ? "Сессия не завершена" : OUTCOME[r.outcome ?? ""] ?? r.outcome ?? "";
  const times = (s?.messages ?? []).map((m) => parseAt(m.at)).filter((d): d is Date => !!d);
  const dur = times.length > 1 ? Math.max(0, Math.round((times[times.length - 1].getTime() - times[0].getTime()) / 1000)) : null;
  const score = card && r.judge ? sessionScore(r.judge.axes, card.difficulty, r.outcome, !!r.walk_away_justified) : null;
  const zone: TargetZone = card?.target_zone ?? { unit: "", user_start: 0, zone_min: 0, zone_max: 0, opponent_start: 0 };
  const ordinal = isOrdinal(zone);
  const subject = cap(zoneSubject(zone) || "итог");
  const findTurn = (quote: string) => {
    const q = norm(quote);
    const i = users.findIndex((u) => norm(u.text).includes(q) || (q.length > 12 && q.includes(norm(u.text))));
    return i < 0 ? null : i;
  };
  const moments = r.judge?.key_moments.map((m) => ({ ...m, turn: findTurn(m.quote) })) ?? [];
  const firstBad = moments.find((m) => m.turn !== null)?.turn;
  const series = s && states.length && states.every((x) => x.after) && s.initial_state
    ? [meters(s.initial_state, s.thresholds), ...states.map((x) => meters(x.after!, s.thresholds))] : null;
  const replayBtn = (i: number) => <button className="replay" onClick={() => replay(i)}><Icon name="replay" size={16} />Переиграть отсюда</button>;
  const axes = Object.entries(r.judge?.axes ?? {});

  return (
    <main className="flush">
        <Scene key={r.outcome ?? r.status} art={outcomeArt(r.status === "active" ? null : r.outcome)} size="wide" className="rhero">
            <div className="crumb">Разбор{card && ` · ${card.name}`}{times[0] && ` · ${dayLabel(times[0])}`}</div>
            <span className={`omark ${tone}`}><span className="dot" />Исход</span>
            <h1>{title}</h1>
            <div className="facts">
              {r.final_position !== null && (ordinal
                ? <div className="fact"><span className="num">{optIndex(zone, r.final_position) + 1} из {zone.options!.length}</span><span className="caps">вариант</span></div>
                : <div className="fact"><span className="num">{fmtValue(r.final_position, zone)}</span><span className="caps">{subject}</span></div>)}
              {s && <div className="fact"><span className="num">{s.turn} / {s.max_turns}</span><span className="caps">ходов</span></div>}
              {dur !== null && dur > 0 && <div className="fact"><span className="num">{Math.floor(dur / 60)}:{String(dur % 60).padStart(2, "0")}</span><span className="caps">длительность</span></div>}
              {score !== null && <div className="fact"><span className="num">{score}</span><span className="caps">балл за сессию</span></div>}
            </div>
            {(r.final_position !== null || r.details_covered.length + r.details_missed.length > 0) && (
              <div className="terms">
                <span className="caps">{r.final_position !== null ? "Условия сделки" : "Детали"}</span>
                {r.final_position !== null && (ordinal
                  ? <span className="tlw"><span className={`dot ${r.in_zone ? "good" : "bad"}`} /><span className="tl">{subject}: <b>{fmtValue(r.final_position, zone)}</b>{r.in_zone === false && " — вне цели"}</span></span>
                  : <span><span className={`dot ${r.in_zone ? "good" : "bad"}`} />{subject} <b>{fmtValue(r.final_position, zone)}</b>{r.in_zone === false && " — вне цели"}</span>)}
                {r.details_covered.map((d) => <span key={d}><span className="dot good" />{cap(d)} — обсудили</span>)}
                {r.details_missed.map((d) => <span key={d}><span className="dot bad" />{cap(d)} — не обсуждали</span>)}
              </div>
            )}
            {r.walk_away_note && <p className="note">{r.walk_away_note}</p>}
            {r.incomplete && <p className="note">Меньше трёх реплик — полный разбор не строим.</p>}
            {err && <p className="error">{err}</p>}
            <div className="acts">
              {r.status === "active"
                ? <button className="primary" onClick={() => go({ name: "dialog", sid })}>Вернуться в диалог</button>
                : s && <button className="primary" onClick={() => startScenario(s.scenario_id, go, setErr)}><Icon name="replay" size={16} />Сыграть заново</button>}
              <button onClick={() => go({ name: "list" })}>К сценариям</button>
            </div>
        </Scene>

        <div className="rgrid">
          <aside>
            {series && series.length > 1 && (
              <div className="panel spark">
                <span className="caps">Динамика</span>
                <h2>Доверие и готовность уступить</h2>
                <Spark trust={series.map((x) => x.trust)} ready={series.map((x) => x.readiness)} mark={firstBad != null ? firstBad + 1 : null} />
                <div className="legend"><span><i style={{ background: "var(--accent)" }} />Доверие</span><span><i className="dash" />Готовность уступить</span><span className="muted">по ходам, %</span></div>
              </div>
            )}
            {r.judge && (
              <div className="panel">
                <span className="caps">Критерии метода · 0–100</span>
                {r.judge_source === "rules" && <p className="small muted">Оценка по правилам: LLM была недоступна.</p>}
                <div className="axes">{axes.map(([k, v]) => (
                  <div key={k} className={`axis ${v < 40 ? "low" : ""}`}>
                    <span className="n">{cap(k)}</span><span className="v num">{v}</span>
                    <div className="track"><div className="fill" style={{ width: `${v}%` }} /></div>
                    {AXIS_WHY[k] && <span className="why">{AXIS_WHY[k]}</span>}
                  </div>
                ))}</div>
                {r.judge.next_scenario_hint && <div className="next"><span className="caps">Дальше</span><p>{r.judge.next_scenario_hint}</p></div>}
              </div>
            )}
          </aside>
          <div>
            {moments.length > 0 && <>
              <div className="mh2"><h2>Ключевые моменты</h2><span className="cap">{moments.length} из {users.length} {users.length === 1 ? "хода" : "ходов"}</span></div>
              <div className="moments">{moments.map((m, i) => (
                <div key={i} className="moment">
                  <div className="head">
                    <span className="caps num">{m.turn !== null ? `Ход ${m.turn + 1}${users[m.turn]?.at ? ` · ${hhmm(parseAt(users[m.turn].at))}` : ""}` : "Реплика"}</span>
                    {m.turn !== null && replayBtn(m.turn)}
                  </div>
                  <q>{m.quote}</q>
                  <div className="two">
                    <div><h4 className="caps bad">Что не так</h4><p>{m.problem}</p></div>
                    <div><h4 className="caps good">Как лучше</h4><p>{m.better}</p></div>
                  </div>
                </div>
              ))}</div>
            </>}
            {users.length > 0 && card && s && <>
              <div className="mh2"><h2>Ваши ходы</h2><span className="cap">приёмы и сдвиг шкал</span></div>
              <ol className="turns">{users.map((m, i) => (
                <li key={i}>
                  <span className="tn num">ход {i + 1}</span>
                  <div><p>{m.text}</p><Marks m={m} before={states[i]?.before ?? null} after={states[i]?.after ?? null} card={card} t={s.thresholds} /></div>
                  {replayBtn(i)}
                </li>
              ))}</ol>
            </>}
          </div>
        </div>
    </main>
  );
}
