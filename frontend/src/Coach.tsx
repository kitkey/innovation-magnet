import { useState } from "react";
import { HintOut, ScenarioCard, store } from "./api";

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

function Close({ onClick }: { onClick: () => void }) {
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
    <section className={`coach ${intro ? "intro" : ""}`} aria-label="Наставления перед переговорами">
      <img className="coach-mascot" src={MASCOT} alt="" />
      <div className="coach-bubble">
        <div className="coach-head">
          <span>{intro ? "Перед началом" : "Наставления"} · {sourceLabel(t.source, method)}</span>
          <span>{i + 1} из {tips.length}</span>
          {!intro && <Close onClick={onDone} />}
        </div>
        <p>{t.text}</p>
        <div className="coach-foot">
          <div className="coach-dots">{tips.map((_, k) => <span key={k} className={k === i ? "on" : ""} />)}</div>
          {intro && !last && <button className="link" onClick={onDone}>Пропустить</button>}
          {i > 0 && <button onClick={() => setI(i - 1)}>Назад</button>}
          {last
            ? <button className="primary" onClick={onDone}>{intro ? "Начать переговоры" : "Понятно"}</button>
            : <button className="primary" onClick={() => setI(i + 1)}>Дальше</button>}
        </div>
      </div>
    </section>
  );
}

type CornerProps = { hints: HintOut[]; method: ScenarioCard["method"]; onOpen: () => void; onClose: () => void };

/** Маскот в углу: по клику открывает наставления; сработавшая подсказка показывается облачком рядом, закрывается крестиком. */
export function CoachCorner({ hints, method, onOpen, onClose }: CornerProps) {
  return (
    <div className="coach-corner">
      {hints.length > 0 && (
        <div className="coach-hint" role="status">
          <Close onClick={onClose} />
          {hints.map((h, k) => (
            <div key={k}>
              <span className="coach-src">{h.source === "standard" ? "Подсказка" : sourceLabel(h.source, method)}</span>
              <p>{h.text}</p>
            </div>
          ))}
        </div>
      )}
      <button className="coach-btn" title="Наставления" aria-label="Открыть наставления" onClick={onOpen}><img src={MASCOT} alt="" /></button>
    </div>
  );
}
