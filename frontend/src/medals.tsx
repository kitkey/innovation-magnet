import { useEffect, useState } from "react";
import { api, Award, Medal, MedalCounts, MedalRule, SeasonState } from "./api";

const MEDALS: Medal[] = ["gold", "silver", "bronze"];
export const MEDAL_RU: Record<Medal, string> = { gold: "Золото", silver: "Серебро", bronze: "Бронза" };

export function MedalDot({ medal, size = 12, title }: { medal: Medal; size?: number; title?: string }) {
  return (
    <svg className={`medal ${medal}`} width={size} height={size} viewBox="0 0 12 12" role="img" aria-label={title ?? MEDAL_RU[medal]}>
      <title>{title ?? MEDAL_RU[medal]}</title>
      <circle cx="6" cy="6" r="5" />
    </svg>
  );
}

export function MedalTally({ counts }: { counts: MedalCounts }) {
  const have = MEDALS.filter((m) => counts[m] > 0);
  if (!have.length) return null;
  return (
    <span className="medal-tally">
      {have.map((m) => <span key={m} title={`${MEDAL_RU[m]}: ${counts[m]}`}><MedalDot medal={m} size={10} />{counts[m]}</span>)}
    </span>
  );
}

function plural(n: number, forms: [string, string, string]) {
  const a = n % 100, b = n % 10;
  return forms[a > 10 && a < 20 ? 2 : b === 1 ? 0 : b >= 2 && b <= 4 ? 1 : 2];
}

/** Та же разбивка, что scoring.medal_split на сервере: подсказка в форме считается до сохранения. */
export function medalSplit(slots: number, gold: number, silver: number): MedalCounts {
  if (slots <= 0) return { gold: 0, silver: 0, bronze: 0 };
  let g = Math.min(slots, Math.floor(slots * gold + 0.5));
  if (g === 0 && gold > 0) g = 1;
  const s = Math.min(slots - g, Math.floor(slots * silver + 0.5));
  return { gold: g, silver: s, bronze: slots - g - s };
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

export function ruleText(r: MedalRule) {
  if (r.slots <= 0) return "Медали в организации выключены.";
  const places = r.slots === 1 ? "первое место" : `первые ${r.slots} ${plural(r.slots, ["место", "места", "мест"])}`;
  return `Медали получают ${places}: золото ${pct(r.gold_share)}, серебро ${pct(r.silver_share)}, остальные бронза.`;
}

export function splitText(c: MedalCounts) {
  const parts = MEDALS.filter((m) => c[m] > 0).map((m) => `${MEDAL_RU[m].toLowerCase()} ${c[m]}`);
  return parts.length ? parts.join(", ") : "без медалей";
}

export const seasonTitle = (name: string) => (/^сезон/i.test(name) ? name : `Сезон «${name}»`);
export const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("ru-RU") : "");
const place = (n: number) => `${n}-е место`;

export function ProfileMedals() {
  const [items, setItems] = useState<Award[]>([]);
  useEffect(() => { api.myMedals().then(setItems).catch(() => setItems([])); }, []);
  if (!items.length) return null;
  return (
    <section className="panel">
      <h3>Медали</h3>
      <ul className="plain medal-list">{items.map((a, i) => (
        <li key={i}><MedalDot medal={a.medal} size={14} />
          <span>{MEDAL_RU[a.medal]} · {place(a.rank)} · {seasonTitle(a.season_name)} · {a.org_name} · {fmtDate(a.awarded_at)}</span></li>
      ))}</ul>
    </section>
  );
}

export function SeasonPanel({ onChanged }: { onChanged: () => void }) {
  const [st, setSt] = useState<SeasonState | null>(null);
  const [slots, setSlots] = useState("10");
  const [gold, setGold] = useState("20");
  const [silver, setSilver] = useState("30");
  const [award, setAward] = useState(true);
  const [reset, setReset] = useState(true);
  const [nextName, setNextName] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const apply = (s: SeasonState) => {
    setSt(s);
    setSlots(String(s.medal_rule.slots)); setGold(String(Math.round(s.medal_rule.gold_share * 100))); setSilver(String(Math.round(s.medal_rule.silver_share * 100)));
    setAward(!s.season.awarded);
  };
  useEffect(() => { api.season().then(apply).catch((e) => setErr(`Сезон не загрузился: ${e.message}`)); }, []);
  if (!st) return err ? <p className="error">{err}</p> : null;

  const n = Math.max(0, Math.floor(Number(slots) || 0));
  const g = (Number(gold) || 0) / 100, s = (Number(silver) || 0) / 100;
  const bad = g < 0 || s < 0 || g + s > 1 + 1e-9;
  const changed = n !== st.medal_rule.slots || Math.abs(g - st.medal_rule.gold_share) > 1e-9 || Math.abs(s - st.medal_rule.silver_share) > 1e-9;
  const run = async (f: () => Promise<SeasonState>, ok: (r: SeasonState) => string) => {
    setErr(""); setMsg(""); setBusy(true);
    try { const r = await f(); apply(r); setMsg(ok(r)); onChanged(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const doClose = () => {
    const steps = [award && "выдать медали по текущему рейтингу сезона", reset && `начать новый сезон${nextName.trim() ? ` «${nextName.trim()}»` : ""}: рейтинг начнётся с нуля, старые сессии останутся в истории`].filter(Boolean);
    if (!confirm(`${seasonTitle(st.season.name)}: ${steps.join("; ")}. Отменить это нельзя.`)) return;
    run(() => api.closeSeason(award, reset, nextName), (r) => {
      const given = "awarded" in r ? (r as { awarded: unknown[] }).awarded.length : 0;
      setNextName("");
      return [award && `Выдано медалей: ${given}`, reset && `Начат ${seasonTitle(r.season.name)}`].filter(Boolean).join(". ");
    });
  };

  return (
    <section className="panel form">
      <h3>Сезон и медали</h3>
      <p>{seasonTitle(st.season.name)}, с {fmtDate(st.season.started_at)}{st.season.awarded ? " · медали выданы" : ""}</p>
      <p className="small muted">Рейтинг в кабинете и лидерборде организации считается по сессиям с начала сезона.</p>

      <div className="medal-form">
        <label>Мест с медалями<input type="number" min={0} max={1000} value={slots} onChange={(e) => setSlots(e.target.value)} /></label>
        <label>Золото, %<input type="number" min={0} max={100} value={gold} onChange={(e) => setGold(e.target.value)} /></label>
        <label>Серебро, %<input type="number" min={0} max={100} value={silver} onChange={(e) => setSilver(e.target.value)} /></label>
      </div>
      <p className="small muted">{bad ? "Золото и серебро в сумме не больше 100%." : n === 0 ? "0 мест: медали выключены." :
        `${n} ${plural(n, ["место", "места", "мест"])}: ${splitText(medalSplit(n, g, s))}. Доли округляются, при ненулевой доле золота одно золото есть всегда. Если людей с рейтингом меньше, чем мест, доли считаются от их числа.`}</p>
      <button disabled={busy || bad || !changed} onClick={() => run(() => api.setMedals(n, g, s), () => "Настройки медалей сохранены")}>Сохранить настройки</button>

      <h3>Закрыть сезон</h3>
      <label className="check"><input type="checkbox" checked={award} disabled={st.season.awarded} onChange={(e) => setAward(e.target.checked)} />
        Выдать медали{st.season.awarded ? " (за этот сезон уже выданы)" : ""}</label>
      <label className="check"><input type="checkbox" checked={reset} onChange={(e) => setReset(e.target.checked)} />Начать новый сезон</label>
      {reset && <label>Название нового сезона<input value={nextName} maxLength={80} onChange={(e) => setNextName(e.target.value)} placeholder={`Сезон ${st.history.filter((h) => h.ended_at).length + 2}`} /></label>}
      <p className="small muted">Медали остаются в профилях навсегда. Без нового сезона рейтинг продолжает копиться, повторно выдать медали за тот же сезон нельзя.</p>
      <button disabled={busy || (!award && !reset) || (award && st.season.awarded && !reset)} onClick={doClose}>Закрыть сезон</button>
      {msg && <p className="note">{msg}</p>}
      {err && <p className="error">{err}</p>}

      {st.history.length > 0 && (
        <>
          <h3>Прошлые сезоны</h3>
          <ul className="plain">{st.history.map((h) => (
            <li key={h.id}>{seasonTitle(h.name)} <span className="muted small">· {fmtDate(h.started_at)}–{h.ended_at ? fmtDate(h.ended_at) : "идёт"} · {h.awarded ? splitText(h.medals) : "без медалей"}</span></li>
          ))}</ul>
        </>
      )}
    </section>
  );
}
