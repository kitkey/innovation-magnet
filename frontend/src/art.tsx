import { ReactNode, useState } from "react";
import { Icon } from "./icons";
import { DOMAIN_ICON } from "./shared";

const ILL = "/illustrations";
export const ART = {
  hero: `${ILL}/scene_01.png`,
  agree: `${ILL}/scene_16.png`,
  breakdown: `${ILL}/out_breakdown_cut.png`,
  walkaway: `${ILL}/out_walkaway_cut.png`,
  folders: `${ILL}/d_folders.png`,
  hourglass: `${ILL}/d_hourglass.png`,
  coffee: `${ILL}/d_coffee.png`,
  podium: `${ILL}/d_podium.png`,
  key: `${ILL}/d_key.png`,
  magnet: `${ILL}/d_magnet.png`,
  team: `${ILL}/grp_team.png`,
};

/** Картинка, которой может ещё не быть на диске: при ошибке загрузки показываем запасной вариант или ничего. */
export function Art({ src, className, fallback = null }: { src: string; className?: string; fallback?: ReactNode }) {
  const [bad, setBad] = useState<string | null>(null);
  if (bad === src) return <>{fallback}</>;
  return <img className={className} src={src} alt="" decoding="async" draggable={false} onError={() => setBad(src)} />;
}

/** Сценка группы по сфере сценария; своя сфера без картинки получает SVG-плитку. */
const GROUP_FILES: [RegExp, string][] = [
  [/закуп|постав|снабж/i, "grp_procurement"],
  [/команд|коллег|руковод|отдел/i, "grp_team"],
  [/проект|заказчик|клиент/i, "grp_project"],
  [/резидент|аренд|оэз|цех/i, "grp_residents"],
  [/карьер|оффер|зарплат|оклад|работодат/i, "grp_career"],
];
export function groupArt(domain: string): string | null {
  const hit = GROUP_FILES.find(([re]) => re.test(domain));
  return hit ? `${ILL}/${hit[1]}.png` : null;
}

export function GroupArt({ domain }: { domain: string }) {
  const tile = <span className="tile"><Icon name={DOMAIN_ICON[domain] ?? "chat"} size={20} /></span>;
  const src = groupArt(domain);
  return src ? <Art className="gart" src={src} fallback={tile} /> : tile;
}

/** Шапка-сцена на всю ширину: текст и иллюстрация в одной контентной колонке, за иллюстрацией — контур арены. */
export function Scene({ art, size = "spot", className = "", children }: { art?: string; size?: "wide" | "spot"; className?: string; children: ReactNode }) {
  const [bad, setBad] = useState<string | null>(null);
  const show = !!art && bad !== art;
  return (
    <section className={`scene fullbleed ${size} ${show ? "has-art" : ""} ${className}`}>
      <div className="in">
        <span className="arena" aria-hidden="true" />
        <div className="txt">{children}</div>
        {show && <div className="art"><img src={art} alt="" decoding="async" draggable={false} onError={() => setBad(art!)} /></div>}
      </div>
    </section>
  );
}

/** Пустое состояние с иллюстрацией. */
export function Empty({ art, title, children }: { art: string; title: string; children?: ReactNode }) {
  return (
    <div className="card emptycard">
      <Art className="eart" src={art} />
      <div><h3>{title}</h3>{children}</div>
    </div>
  );
}
