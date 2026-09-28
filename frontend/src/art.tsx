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

/** Значки групп: имя файла grp_<имя>.png и подпись для выбора в форме. Список совпадает с DomainIcon на сервере. */
export const GROUP_ICONS: [string, string][] = [
  ["procurement", "Закупки"], ["sales", "Продажи"], ["service", "Клиентский сервис"], ["finance", "Финансы"], ["legal", "Юристы и договоры"],
  ["logistics", "Логистика"], ["production", "Производство"], ["it", "IT и разработка"], ["hr", "HR и найм"], ["marketing", "Маркетинг"],
  ["government", "Госорганы"], ["startup", "Стартап и инвесторы"], ["career", "Карьера"], ["team", "Работа в команде"],
  ["project", "Проекты и заказчики"], ["residents", "Резиденты и площадки"], ["everyday", "Быт и повседневное"],
];

/** Значок по словам сферы. Порядок важен: узкие сферы раньше общих («Аренда жилья» — быт, а не резиденты). */
const GROUP_FILES: [RegExp, string][] = [
  [/закуп|постав|снабж|тендер/i, "procurement"],
  [/продаж|магазин|торгов|покупател|ритейл/i, "sales"],
  [/сервис|поддержк|обслуживан|жалоб|претензи/i, "service"],
  [/финанс|бюджет|банк|кредит|бухгалт|платеж/i, "finance"],
  [/юри|договор|суд|правов|контракт/i, "legal"],
  [/логист|доставк|склад|перевоз|транспорт/i, "logistics"],
  [/производ|завод|фабрик|станк/i, "production"],
  [/\bit\b|айти|(^|[\s-])ит([\s-]|$)|разработ|программ|софт/i, "it"],
  [/\bhr\b|найм|кадр|персонал|рекрут/i, "hr"],
  [/маркет|реклам|бренд|smm|продвижен/i, "marketing"],
  [/госорган|государ|министер|администрац|ведомств|муницип|чиновн/i, "government"],
  [/стартап|инвестор|венчур|основател/i, "startup"],
  [/карьер|оффер|зарплат|оклад|работодат|трудоустр/i, "career"],
  [/команд|коллег|руковод|отдел/i, "team"],
  [/проект|заказчик|клиент|фриланс/i, "project"],
  [/быт|повседнев|сосед|квартир|жиль|семь|ремонт|учёб|учеб|универ|студен/i, "everyday"],
  [/резидент|аренд|оэз|цех/i, "residents"],
];
export const iconSrc = (name: string) => `${ILL}/grp_${name}.png`;
export function autoIcon(domain: string): string | null {
  return GROUP_FILES.find(([re]) => re.test(domain))?.[1] ?? null;
}
export function groupArt(domain: string, icon?: string | null): string | null {
  const name = icon || autoIcon(domain);
  return name ? iconSrc(name) : null;
}

/** Значок группы: выбранный автором первого сценария группы, иначе по словам сферы, иначе SVG-плитка. */
export function GroupArt({ domain, icon }: { domain: string; icon?: string | null }) {
  const tile = <span className="tile"><Icon name={DOMAIN_ICON[domain] ?? "chat"} size={20} /></span>;
  const src = groupArt(domain, icon);
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
