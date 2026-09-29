import { useState } from "react";
import { HintOut, ScenarioCard, store } from "./api";
import { Art, ART } from "./art";

export const MASCOT = "/mascot/mascot.png";
const METHOD_RU: Record<ScenarioCard["method"], string> = { spin: "по методу SPIN", harvard: "по Гарвардскому методу", batna: "по методу BATNA", free: "общее" };

// Одно наставление по слабой стороне из входного теста (arena.test → weak)
const WEAK_TIP: Record<string, string> = {
  interests: "Тест показал, что вы редко выясняете интересы. Прежде чем спорить, спросите, зачем собеседнику его условие.",
  criteria: "Тест показал, что вам не хватает опоры на критерии. Подготовьте для своей цифры один внешний довод: рынок, регламент, прошлый опыт.",
  emotions: "Тест показал, что резкий тон выбивает вас из колеи. На колкость отвечайте уточняющим вопросом, а не аргументом.",
  offers: "Тест показал, что вы уступаете слишком легко. Каждую уступку отдавайте только в обмен на встречное условие.",
  batna: "Тест показал, что вы забываете про альтернативу. Сравнивайте с ней каждое предложение собеседника.",
};

export function weakTip(): HintOut | null {
  try {
    const weak = JSON.parse(store.get("arena.test") ?? "null")?.weak;
    return weak && WEAK_TIP[weak] ? { text: WEAK_TIP[weak], source: "test" } : null;
  } catch { return null; }
}

/** Наставления перед стартом: свои от организации или автора, стандартные по методу, одно по входному тесту. */
export function coachTips(coach: HintOut[] | undefined): HintOut[] {
  const own = (coach ?? []).filter((t) => t.source !== "standard");
  const std = (coach ?? []).filter((t) => t.source === "standard");
  const weak = weakTip();
  return [...own, ...std, ...(weak ? [weak] : [])];
}

export function sourceLabel(src: HintOut["source"], method: ScenarioCard["method"]): string {
  if (src === "org") return "от организации";
  if (src === "author") return "от автора сценария";
  if (src === "test") return "по входному тесту";
  return METHOD_RU[method];
}

export function Close({ onClick }: { onClick: () => void }) {
  return (
    <button className="coach-x" aria-label="Закрыть" onClick={onClick}>
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
    </button>
  );
}

type PanelProps = { tips: HintOut[]; method: ScenarioCard["method"]; intro: boolean; onDone: () => void };

/** Маскот с облачком наставлений: листаются «Дальше», в начале диалога последняя кнопка — «Начать переговоры». */
export function CoachPanel({ tips, method, intro, onDone }: PanelProps) {
  const [i, setI] = useState(0);
  if (!tips.length) return null;
  const t = tips[Math.min(i, tips.length - 1)];
  const last = i >= tips.length - 1;
  return (
    <section className={`coach ${intro ? "intro" : "modal"}`} aria-label="Наставления перед переговорами" onClick={intro ? undefined : (e) => { if (e.target === e.currentTarget) onDone(); }}>
      {intro && <div className="empty"><Art className="hg" src={ART.hourglass} fallback={<svg className="i" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" /></svg>} /><span><b>Переписка пока пуста</b>Собеседник начнёт первым, когда вы прочитаете наставления.</span></div>}
      <div className="crow">
        <img className="coach-mascot" src={MASCOT} alt="" />
        <div className="coach-bubble">
          <div className="coach-head">
            <span className="caps">{intro ? "Перед началом" : "Наставления"} · {sourceLabel(t.source, method)}</span>
            <span className="cap num">{i + 1} из {tips.length}{!intro && <Close onClick={onDone} />}</span>
          </div>
          <p>{t.text}</p>
          <div className="coach-foot">
            <div className="coach-dots">{tips.map((_, k) => <span key={k} className={k === i ? "on" : ""} />)}</div>
            {intro && !last && <button className="ghost" onClick={onDone}>Пропустить</button>}
            {i > 0 && <button className="ghost" onClick={() => setI(i - 1)}>Назад</button>}
            {last
              ? <button className="primary" onClick={onDone}>{intro ? "Начать переговоры" : "Понятно"}</button>
              : <button className="primary" onClick={() => setI(i + 1)}>Дальше<Arrow /></button>}
          </div>
        </div>
      </div>
    </section>
  );
}

function Arrow() {
  return <svg className="i" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
}

export function hintSource(h: HintOut, method: ScenarioCard["method"]): string {
  return h.source === "standard" ? "Подсказка" : sourceLabel(h.source, method);
}

type CornerProps = { hints: HintOut[]; method: ScenarioCard["method"]; onOpen: () => void; onClose: () => void };

/** Маскот в углу: по клику открывает наставления; сработавшая подсказка показывается облачком рядом, закрывается крестиком. */
export function CoachCorner({ hints, method, onOpen, onClose }: CornerProps) {
  return (
    <div className="buddy">
      <button className="coach-btn" title="Наставления" aria-label="Открыть наставления" onClick={onOpen}><img src={MASCOT} alt="" /></button>
      {hints.length > 0 && (
        <div className="coach-hint" role="status">
          <Close onClick={onClose} />
          {hints.map((h, k) => (
            <div key={k}>
              <span className="coach-src">{hintSource(h, method)}</span>
              <p>{h.text}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Та же подсказка на телефоне: блоком в ленте сразу после хода, к которому относится. */
export function InlineHint({ hints, method, onClose }: { hints: HintOut[]; method: ScenarioCard["method"]; onClose: () => void }) {
  if (!hints.length) return null;
  return (
    <div className="ihint" role="status">
      <img src={MASCOT} alt="" />
      <div>{hints.map((h, k) => <div key={k}><span className="coach-src">{hintSource(h, method)}</span><p>{h.text}</p></div>)}</div>
      <Close onClick={onClose} />
    </div>
  );
}
