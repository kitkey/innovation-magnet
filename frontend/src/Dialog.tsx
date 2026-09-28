import { useEffect, useRef, useState } from "react";
import { api, fmtValue, HintOut, Message, MODE_KEY, Mood, ScenarioCard, SessionView, store, TurnOut, unitParts, VoiceStatus } from "./api";
import type { Say } from "./avatar/Avatar3D";
import { CoachCorner, CoachPanel, coachTips, InlineHint } from "./Coach";
import { Icon } from "./icons";
import OpponentAvatar, { OpponentMode } from "./OpponentAvatar";
import { ACTIVE_KEY, cap, Delta, Go, hhmm, initials, Marks, meters, oppName, parseAt, RU, STYLE_RU, turnStates, who } from "./shared";
import Recorder from "./voice/Recorder";

const MOOD_RU: Record<Mood, [string, string]> = {
  neutral: ["спокойное", ""], happy: ["доброжелательное", "good"], angry: ["раздражённое", "bad"], sad: ["подавленное", "warn"], disgust: ["недовольное", "warn"],
};

function Segs({ n, of }: { n: number; of: number }) {
  return <span className="segs">{Array.from({ length: Math.min(of, 20) }, (_, i) => <i key={i} className={i < n ? "on" : ""} />)}</span>;
}

function ModeTabs({ mode, setMode }: { mode: OpponentMode; setMode: (m: OpponentMode) => void }) {
  return (
    <div className="tabs" role="group" aria-label="Режим собеседника">
      {([["text", "Текст"], ["avatar", "3D и голос"]] as [OpponentMode, string][]).map(([v, t]) => (
        <button key={v} className={mode === v ? "on" : ""} aria-pressed={mode === v} onClick={() => setMode(v)}>{t}</button>
      ))}
    </div>
  );
}

/** Шкала торга: только то, что игрок уже знает — своя стартовая позиция, старт и текущая позиция собеседника. Целевая зона не показывается. */
function PriceScale({ card, position }: { card: ScenarioCard; position: number }) {
  const z = card.target_zone;
  const { subject, short } = unitParts(z.unit);
  const vals = [z.user_start, z.opponent_start, position];
  const lo = Math.min(...vals), hi = Math.max(...vals) === lo ? lo + 1 : Math.max(...vals);
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const edge = (v: number) => (x(v) < 12 ? "l" : x(v) > 88 ? "r" : "");
  const f = (v: number) => fmtValue(v, z.unit);
  return (
    <div className="pos">
      <div className="caps">{cap(subject || card.topic)}, {short}</div>
      <div className="scale" aria-label={`Ваш старт ${f(z.user_start)}, собеседник сейчас ${f(position)}`}>
        <div className="ln" />
        <div className="gap" style={{ left: `${Math.min(x(z.user_start), x(position))}%`, width: `${Math.abs(x(position) - x(z.user_start))}%` }} />
        <div className={`pt opp ${edge(position)}`} style={{ left: `${x(position)}%` }}><i /><span>{f(position)} собеседник</span></div>
        <div className={`pt me ${edge(z.user_start)}`} style={{ left: `${x(z.user_start)}%` }}><i /><span>{f(z.user_start)} ваш старт</span></div>
        {position !== z.opponent_start && <div className={`pt st ${edge(z.opponent_start)}`} style={{ left: `${x(z.opponent_start)}%` }}><i /><span>{f(z.opponent_start)} его старт</span></div>}
      </div>
    </div>
  );
}

/** Бриф: только то, что знает игрок. Скрытые интересы, альтернатива собеседника и целевая зона сюда не попадают. */
function BriefBody({ card, clamp }: { card: ScenarioCard; clamp: boolean }) {
  const [full, setFull] = useState(false);
  const { subject, short } = unitParts(card.target_zone.unit);
  return (
    <>
      {card.context && <section><span className="caps">Ситуация</span>
        <p className={clamp && !full ? "clamp" : ""}>{card.context}</p>
        {clamp && card.context.length > 180 && <button className="link" onClick={() => setFull(!full)}>{full ? "Свернуть" : "Показать полностью"}</button>}
      </section>}
      <section><span className="caps">Ваша роль</span><p>{card.user_role}</p></section>
      <section><span className="caps">Ваша цель</span><p>{card.user_goal}</p></section>
      {card.user_batna && <section><span className="caps">Ваша альтернатива</span><p>{card.user_batna}{card.method === "batna" && ". Если сделка хуже неё, можно выйти из переговоров."}</p></section>}
      <section><span className="caps">Предмет торга</span><p>{cap(subject || card.topic)} ({short}); вы начинаете с {fmtValue(card.target_zone.user_start, card.target_zone.unit)}</p></section>
    </>
  );
}

export default function Dialog({ sid, go }: { sid: string; go: Go }) {
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
  const [hinted, setHinted] = useState<Set<number>>(new Set());
  const [hintTurn, setHintTurn] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [menu, setMenu] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const setMode = (m: OpponentMode) => { setModeState(m); store.set(MODE_KEY, m); if (m === "text") setSpeaking(false); };
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
  useEffect(() => { const el = logRef.current; if (el) el.scrollTop = el.scrollHeight; }, [s?.messages.length, busy, hints.length, intro]);
  useEffect(() => {
    const ta = taRef.current, el = logRef.current;
    const atBottom = !!el && el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    if (ta) { ta.style.height = "auto"; ta.style.height = `${Math.min(ta.scrollHeight + 2, 180)}px`; }
    if (el && atBottom) el.scrollTop = el.scrollHeight;
  }, [msg]);

  const apply = (base: SessionView, user: Message, r: TurnOut) => {
    const now = new Date().toISOString();
    setS({
      ...base, turn: r.turn, status: r.status, outcome: r.outcome, state: r.state, mood: r.mood,
      messages: [...base.messages, { ...user, state: r.state, at: now }, { role: "opponent", text: r.opponent_message, labels: [], at: now }],
    });
    setSay({ id: r.turn, text: r.opponent_message, mood: r.mood });
    if (r.hints?.length) { setHints(r.hints); setHintTurn(r.turn); setHinted((h) => new Set(h).add(r.turn)); }
    // В режиме 3D даём собеседнику договорить последнюю реплику, потом открываем разбор
    if (r.status === "finished") { store.set(ACTIVE_KEY, null); window.setTimeout(() => go({ name: "result", sid }), mode === "avatar" ? 6000 : 0); }
  };

  const send = async () => {
    if (!s || !msg.trim() || busy) return;
    const text = msg;
    setBusy(true); setErr(""); setHints([]);
    setS({ ...s, messages: [...s.messages, { role: "user", text, labels: [], pending: true, at: new Date().toISOString() }] });
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
    setBusy(true); setErr(""); setHints([]);
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
    setMenu(false); setBusy(true); setErr("");
    try { await api.finish(sid); store.set(ACTIVE_KEY, null); go({ name: "result", sid }); } catch (e) { setErr(`Не удалось завершить: ${(e as Error).message}`); } finally { setBusy(false); }
  };
  const undo = async () => {
    if (!s) return;
    setMenu(false); setBusy(true); setErr("");
    try { const v = await api.rewind(sid, s.turn - 1); store.set(ACTIVE_KEY, v.id); go({ name: "dialog", sid: v.id }); } catch (e) { setErr(`Не удалось отменить ход: ${(e as Error).message}`); } finally { setBusy(false); }
  };

  if (!s) return <div className="page"><main>{err ? <p className="error">{err}</p> : <p className="muted">Загрузка…</p>}</main></div>;
  const card = s.card;
  const t = s.thresholds;
  const ready = !busy && s.status === "active" && !intro;
  const tips = coachTips(s.coach);
  const name = oppName(card);
  const m = meters(s.state, t);
  const states = turnStates(s);
  const last = states[states.length - 1];
  const lastM = last?.before && last.after ? meters(last.before, t) : null;
  const d = (k: keyof typeof m) => (lastM ? m[k] - lastM[k] : 0);
  const [moodWord, moodTone] = MOOD_RU[s.mood ?? "neutral"] ?? MOOD_RU.neutral;
  const status = intro ? ["Ждёт начала", ""] : busy ? ["Готовит ответ", ""] : speaking && mode === "avatar" ? ["Говорит", "eq"] : ["Ждёт вашего ответа", "live"];
  const meta = [card.domain, `метод ${RU[card.method]}`, `${RU[card.difficulty]} сложность`, `собеседник ${STYLE_RU[card.style] ?? RU[card.style]}`].filter(Boolean).join(" · ");
  const openTips = () => { setMenu(false); setHints([]); setTipsOpen(true); };
  let userN = 0;

  const meterRow = (label: string, v: number, dv: number, warn: boolean, title: string) => (
    <div className="meter" title={title}>
      <span>{label}</span>
      <span className="d num">{dv ? <Delta d={dv} /> : "—"}</span>
      <span className="v num">{v}%</span>
      <div className="track"><div className={`fill ${v < 20 ? "low" : warn ? "warn" : ""}`} style={{ width: `${v}%` }} /></div>
    </div>
  );

  return (
    <div className="dshell">
      <header className="dtop">
        <button className="ghost icon" aria-label="К сценариям" title="К сценариям (сессию можно продолжить)" onClick={() => go({ name: "list" })}><Icon name="back" /></button>
        <div className="t">
          <b>{card.name}</b>
          <span>{meta}</span>
          <em>ход {s.turn} из {s.max_turns} · {name}</em>
        </div>
        <div className="turnc desk"><span className="num">Ход {s.turn} из {s.max_turns}</span><Segs n={s.turn} of={s.max_turns} /></div>
        <div className="desk seg-desk"><ModeTabs mode={mode} setMode={setMode} /></div>
        <button className="desk" disabled={!ready || s.turn === 0} onClick={undo}><Icon name="undo" />Отменить ход</button>
        <button className="desk" disabled={!ready} onClick={finish}><Icon name="flag" />Завершить</button>
        <div className="dmore">
          <button className="ghost icon" aria-label="Меню сессии" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name="more" /></button>
          {menu && (
            <div className="dmenu">
              <ModeTabs mode={mode} setMode={(v) => { setMode(v); setMenu(false); }} />
              {tips.length > 0 && !intro && <button onClick={openTips}><Icon name="book" />Наставления</button>}
              <button disabled={!ready || s.turn === 0} onClick={undo}><Icon name="undo" />Отменить ход</button>
              <button disabled={!ready} onClick={finish}><Icon name="flag" />Завершить</button>
            </div>
          )}
        </div>
      </header>
      <div className="mseg" aria-hidden="true">{Array.from({ length: Math.min(s.max_turns, 20) }, (_, i) => <i key={i} className={i < s.turn ? "on" : ""} />)}</div>
      <div className="dgrid">
        <aside className="oppcol">
          {mode === "avatar"
            ? (
              <div className="stage">
                <OpponentAvatar role={who(card)} mode={mode} avatarUrl={card.avatar_url ?? null} gender={card.voice ?? "female"}
                  mood={s.mood ?? "neutral"} say={vs === undefined || intro ? null : say} ttsReady={!!vs?.tts} onSpeaking={setSpeaking} />
                <div className="status">{status[1] === "eq" ? <span className="eq"><i /><i /><i /><i /></span> : <span className={`dot ${status[1]}`} />}{status[0]}</div>
              </div>
            )
            : (
              <div className="stage textmode">
                <div className="mono" aria-hidden="true">{initials(name)}</div>
                <div className="status"><span className={`dot ${status[1] === "eq" ? "live" : status[1]}`} />{status[0]}</div>
              </div>
            )}
          <div className="whoopp">
            <div><b>{name}</b>{card.opponent_name?.trim() && <span className="role">{card.opponent_role}</span>}</div>
            <span className="mood"><span className={`dot ${moodTone}`} />настроение: {moodWord}</span>
          </div>
          <div className="meters">
            {meterRow("Доверие", m.trust, d("trust"), false, "Растёт от вопросов об интересах и эмпатии, падает от давления")}
            {meterRow("Терпение", m.patience, d("patience"), m.patience < 45, "Когда кончится, собеседник прервёт переговоры")}
            {meterRow("Готовность уступить", m.readiness, d("readiness"), false, "На 100% собеседник сдвигает позицию")}
          </div>
          <div className="mmeters">
            <div><span className="caps">Доверие</span><b className="num">{m.trust}{d("trust") !== 0 && <span><Delta d={d("trust")} /></span>}</b></div>
            <div><span className="caps">Терпение</span><b className="num">{m.patience}{d("patience") !== 0 && <span><Delta d={d("patience")} /></span>}</b></div>
            <div><span className="caps">Уступить</span><b className="num">{m.readiness}{d("readiness") !== 0 && <span><Delta d={d("readiness")} /></span>}</b></div>
            <div><span className="caps">Позиция</span><b className="num">{fmtValue(s.state.position, card.target_zone.unit)}</b></div>
          </div>
          <PriceScale card={card} position={s.state.position} />
          <details className="brief-m"><summary>Ситуация и цель</summary><div className="bm"><BriefBody card={card} clamp={false} /></div></details>
        </aside>

        <section className="chat">
          {intro
            ? <CoachPanel tips={tips} method={card.method} intro onDone={() => setIntro(false)} />
            : (
              <div className="log" ref={logRef} aria-live="polite">
                {s.messages.map((mm, i) => {
                  if (mm.role === "opponent") return (
                    <div key={i} className="rep opp">
                      <div className="mh"><b>{name}</b><span className="num">{hhmm(parseAt(mm.at))}</span></div>
                      <p>{mm.text}</p>
                    </div>
                  );
                  const n = ++userN;
                  const st = states[n - 1];
                  return (
                    <div key={i} className="grp" style={{ display: "contents" }}>
                      <div className={`rep user ${mm.pending ? "pending" : ""}`}>
                        <div className="mh"><span className="num">ход {n}{mm.at && ` · ${hhmm(parseAt(mm.at))}`}</span><b>Вы</b></div>
                        <div className="body">
                          {mm.audio_url && <audio controls preload="none" src={mm.audio_url} />}
                          <p>{mm.text}</p>
                          {!mm.pending && <Marks m={mm} before={st?.before ?? null} after={st?.after ?? null} card={card} t={t} hinted={hinted.has(n)} />}
                        </div>
                      </div>
                      {n === hintTurn && <InlineHint hints={hints} method={card.method} onClose={() => setHints([])} />}
                    </div>
                  );
                })}
                {busy && <div className="typing"><span className="dots"><i /><i /><i /></span>{name} отвечает</div>}
              </div>
            )}
          <div className={`input ${intro ? "pre" : ""}`}>
            {err && <p className="error" role="alert">{err}</p>}
            <div className="field">
              <textarea ref={taRef} rows={1} value={msg} maxLength={2500} disabled={!ready} aria-label="Ваша реплика" onChange={(e) => setMsg(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder={intro ? "Первым говорит собеседник, ввод откроется после наставлений" : "Ваша реплика"} />
              <Recorder disabled={!ready} sttReady={!!vs?.stt} maxSeconds={vs?.max_seconds ?? 30} onSend={sendVoice} onError={setErr} />
              <button className="primary" aria-label="Отправить" title="Отправить" disabled={!ready || !msg.trim()} onClick={send}><Icon name="send" size={20} /></button>
            </div>
            <div className="hints">
              <span className="kh"><kbd>Enter</kbd> отправить · <kbd>Shift</kbd> + <kbd>Enter</kbd> перенос строки{vs?.stt && <> · удерживайте микрофон для голоса</>}</span>
              <span className="num">{msg.length}/2500</span>
            </div>
          </div>
        </section>

        <aside className="side">
          <BriefBody card={card} clamp />
          <div className="spacer" />
          {!intro && tips.length > 0 && <CoachCorner hints={hints} method={card.method} onOpen={openTips} onClose={() => setHints([])} />}
        </aside>
      </div>
      {!intro && tipsOpen && <CoachPanel tips={tips} method={card.method} intro={false} onDone={() => setTipsOpen(false)} />}
    </div>
  );
}
