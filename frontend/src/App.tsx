import { useEffect, useState } from "react";
import { Auth, Leaderboard, OrgCabinet, Profile } from "./account";
import { ART, autoIcon, Empty, GROUP_ICONS, iconSrc, Scene } from "./art";
import { api, AUTH_KEY, Character, Hint, HistoryItem, isOrdinal, Scenario, ScenarioCard, store, TargetZone, User } from "./api";
import Dialog from "./Dialog";
import Home, { SessionRow } from "./Home";
import { Icon } from "./icons";
import Result from "./Result";
import { FIELD_HELP, FieldLabel, ScenarioHelp } from "./scenarioHelp";
import { Go, initials, LABEL_RU, plural, recommend, RU, startScenario, TEST_KEY, View, Weak, WEAK_RU } from "./shared";

const EMPTY: ScenarioCard = {
  name: "", domain: "", topic: "", difficulty: "medium", tone: "neutral", method: "free", style: "hard",
  user_role: "", user_goal: "", opponent_role: "", opponent_name: "", opponent_goal: "", opponent_hidden_interests: [],
  opponent_batna: "", user_batna: "", target_zone: { unit: "", user_start: 0, zone_min: 0, zone_max: 0, opponent_start: 0 },
  mandatory_details: [], context: "", opening: "", max_turns: 10, locked_by_org: false, voice: "female", avatar_url: null, domain_icon: null,
  coach_tips: [], hints: [],
};

const NAV: [View["name"], string][] = [["list", "Сценарии"], ["setup", "Новый сценарий"], ["history", "История"], ["leaderboard", "Лидерборд"], ["org", "Организация"], ["test", "Входной тест"]];

export default function App() {
  const [view, setViewState] = useState<View>(() => (store.get(TEST_KEY) ? { name: "list" } : { name: "test" }));
  const [user, setUser] = useState<User | null>(null);
  const [menu, setMenu] = useState(false);
  const setView = (v: View) => { setMenu(false); setViewState(v); window.scrollTo(0, 0); };
  useEffect(() => {
    if (store.get(AUTH_KEY)) api.me().then(setUser).catch(() => store.set(AUTH_KEY, null));
  }, []);
  const onUser = (u: User | null) => { setUser(u); setView(u ? { name: "profile" } : { name: "list" }); };
  if (view.name === "dialog") return <Dialog key={view.sid} sid={view.sid} go={setView} />;
  const nav = NAV.filter(([n]) => n !== "org" || user?.role === "org_admin");
  const current = view.name === "result" ? "history" : view.name;
  const toUser = () => setView(user ? { name: "profile" } : { name: "auth" });
  return (
    <div className="app">
      <header className="top">
        <button className="brand" onClick={() => setView({ name: "list" })}><Icon name="logo" size={20} />Арена переговоров</button>
        <nav className="nav">{nav.map(([n, t]) => <button key={n} className={current === n ? "on" : ""} aria-current={current === n ? "page" : undefined} onClick={() => setView({ name: n } as View)}>{t}</button>)}</nav>
        <button className="who" onClick={toUser}>
          {user
            ? <><div>{user.display_name}{user.org_name && <small>{user.org_name}</small>}</div><span className="ava">{initials(user.display_name)}</span></>
            : <><div>Войти<small>гостевой режим</small></div><span className="ava"><Icon name="user" size={16} /></span></>}
        </button>
        <button className="ghost icon burger" aria-label="Меню" aria-expanded={menu} onClick={() => setMenu(!menu)}><Icon name={menu ? "x" : "menu"} /></button>
        {menu && (
          <div className="navmenu">
            {nav.map(([n, t]) => <button key={n} className={current === n ? "on" : ""} onClick={() => setView({ name: n } as View)}>{t}</button>)}
            <button onClick={toUser}><Icon name="user" size={16} />{user ? user.display_name : "Войти"}</button>
          </div>
        )}
      </header>
      <div className="page">
        {view.name === "list" && <Home key={user?.id ?? "guest"} user={user} go={setView} />}
        {view.name === "setup" && <Setup key={`${view.scenario?.id ?? "new"}-${view.copy ? "copy" : "edit"}`} scenario={view.scenario} copy={view.copy} go={setView} />}
        {view.name === "result" && <Result key={view.sid} sid={view.sid} go={setView} />}
        {view.name === "history" && <History go={setView} />}
        {view.name === "test" && <EntryTest go={setView} />}
        {view.name === "auth" && <Auth onUser={onUser} />}
        {view.name === "profile" && (user ? <Profile user={user} onUser={(u) => (u ? setUser(u) : onUser(null))} /> : <Auth onUser={onUser} />)}
        {view.name === "org" && (user?.role === "org_admin" ? <OrgCabinet key={user.org_id} user={user} onUser={setUser} /> : <main><p className="muted">Кабинет доступен администратору организации.</p></main>)}
        {view.name === "leaderboard" && <Leaderboard key={user?.id ?? "guest"} user={user} />}
      </div>
    </div>
  );
}

function AvatarField({ value, onChange }: { value: string | null; onChange: (url: string | null, voice?: Character["voice"]) => void }) {
  const [info, setInfo] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [chars, setChars] = useState<Character[]>([]);
  useEffect(() => { api.characters().then(setChars).catch(() => setChars([])); }, []);
  const upload = async (f: File | undefined) => {
    if (!f) return;
    setErr(""); setInfo(""); setBusy(true);
    try {
      const r = await api.uploadAvatar(f);
      onChange(r.url);
      setInfo(`Загружено: ${(r.size / 1048576).toFixed(1)} МБ, визем ${r.visemes}. ${r.warnings.join(". ")}`);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const picked = chars.find((c) => c.url === value);
  const own = value && !picked;
  return (
    <fieldset><legend>Персонаж собеседника</legend>
      <p className="small muted">Кого вы увидите в режиме «3D и голос». Голос подставится по полу персонажа, его можно сменить выше.</p>
      <div className="char-grid" role="radiogroup" aria-label="Персонаж собеседника">
        {chars.map((c) => (
          <button type="button" key={c.id} role="radio" aria-checked={c.url === value} disabled={!c.ready}
            className={`char ${c.url === value ? "on" : ""}`} onClick={() => onChange(c.url, c.voice)}
            title={c.ready ? `${c.name}, ${c.style === "chibi" ? "чиби" : "Pixar"}` : "Скоро"}>
            <img src={c.portrait} alt="" loading="lazy" width={96} height={96} />
            <span className="char-name">{c.name}</span>
            <span className="char-meta">{c.style === "chibi" ? "чиби" : "Pixar"} · {c.voice === "female" ? "жен." : "муж."}</span>
            {!c.ready && <span className="char-soon">скоро</span>}
          </button>
        ))}
      </div>
      <p className="small muted">{own ? `Свой аватар: ${value}` : picked ? `Выбран: ${picked.name}, ${picked.style === "chibi" ? "чиби" : "Pixar"}.` : "Не выбран: подберём чиби по голосу."} Свой GLB — со скелетом в стиле Mixamo, виземами Oculus и ARKit-блендшейпами; как сделать — в README.</p>
      <div className="row">
        <label className="file">{busy ? "Загружаем…" : "Загрузить свой GLB"}<input type="file" accept=".glb,model/gltf-binary" disabled={busy} onChange={(e) => upload(e.target.files?.[0])} /></label>
        {value && <button type="button" onClick={() => onChange(null)}>Сбросить выбор</button>}
      </div>
      {info && <p className="small">{info}</p>}
      {err && <p className="error">{err}</p>}
    </fieldset>
  );
}

const HINT_LABELS = ["pressure", "concession", "personal_attack", "manipulation", "vague", "batna_reference", "boundary", "conditional_trade", "concrete_offer", "empathy", "interest_question", "objective_criterion"];
const HINT_MISSING = ["interest_question", "objective_criterion", "batna_reference", "conditional_trade", "concrete_offer", "boundary", "empathy", "mandatory_detail", "spin_problem", "spin_implication", "spin_need_payoff"];
const HINT_KINDS: [string, string][] = [
  ...HINT_LABELS.map((l): [string, string] => [`label:${l}`, `В ходе игрока: ${LABEL_RU[l]}`]),
  ...HINT_MISSING.map((l): [string, string] => [`missing:${l}`, `К ходу N ни разу не было: ${LABEL_RU[l]}`]),
  ["irritation_high", "Собеседник на грани срыва"], ["trust_low", "Доверие упало"], ["readiness_high", "Собеседник почти готов уступить"],
  ["turns_left", "Осталось N ходов или меньше"],
];

/** «missing:empathy@3» → вид условия «missing:empathy» и число 3. */
function splitWhen(when: string): { kind: string; n: number } {
  const m = when.match(/^(missing:[a-z_]+)@(\d+)$/) ?? when.match(/^(turns_left):(\d+)$/);
  return m ? { kind: m[1], n: Number(m[2]) } : { kind: when, n: 0 };
}

function joinWhen(kind: string, n: number): string {
  if (kind.startsWith("missing:")) return `${kind}@${n || 3}`;
  if (kind === "turns_left") return `turns_left:${n || 2}`;
  return kind;
}

function HintsField({ value, maxTurns, onChange }: { value: Hint[]; maxTurns: number; onChange: (v: Hint[]) => void }) {
  const put = (i: number, h: Hint) => onChange(value.map((x, k) => (k === i ? h : x)));
  return (
    <fieldset className="hints-field"><legend>Подсказки по ходу диалога</legend>
      <p className="small muted">Маскот покажет подсказку один раз, когда выполнится условие. Стандартные подсказки по методу работают всегда, ваши показываются первыми.</p>
      {value.map((h, i) => {
        const { kind, n } = splitWhen(h.when);
        const needsN = kind.startsWith("missing:") || kind === "turns_left";
        return (
          <div key={i} className="hint-row">
            <label>Когда
              <div className="hint-when">
                <select value={kind} onChange={(e) => put(i, { ...h, when: joinWhen(e.target.value, n) })}>
                  {HINT_KINDS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </select>
                {needsN && <input type="number" min={1} max={maxTurns} value={n} aria-label="N" onChange={(e) => put(i, { ...h, when: joinWhen(kind, Number(e.target.value)) })} />}
              </div>
            </label>
            <label>Текст подсказки<input value={h.text} maxLength={300} placeholder="Одна-две строки: что сделать иначе" onChange={(e) => put(i, { ...h, text: e.target.value })} /></label>
            <button className="hint-del" title="Удалить подсказку" aria-label="Удалить подсказку" onClick={() => onChange(value.filter((_, k) => k !== i))}>
              <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" /></svg>
            </button>
          </div>
        );
      })}
      {value.length < 20 && <button className="add" onClick={() => onChange([...value, { when: "label:concession", text: "" }])}>Добавить подсказку</button>}
    </fieldset>
  );
}

function IconPicker({ domain, value, onChange }: { domain: string; value: string | null; onChange: (v: string | null) => void }) {
  const auto = autoIcon(domain);
  const autoLabel = auto ? GROUP_ICONS.find(([n]) => n === auto)?.[1] : null;
  return (
    <fieldset className="icon-pick"><legend><FieldLabel label="Значок группы" help={FIELD_HELP.domain_icon} /></legend>
      <p className="small muted">{value ? "Выбран вручную." : autoLabel ? `Авто: «${autoLabel}», по слову в сфере.` : "Авто: по сфере значок не подобрался, в списке будет плитка."}</p>
      <div className="icon-grid" role="radiogroup" aria-label="Значок группы">
        <button type="button" role="radio" aria-checked={!value} className={`ic-auto ${!value ? "on" : ""}`} onClick={() => onChange(null)}>Авто</button>
        {GROUP_ICONS.map(([n, t]) => (
          <button key={n} type="button" role="radio" aria-checked={value === n} title={t} aria-label={t}
            className={`${value === n ? "on" : ""} ${!value && auto === n ? "auto" : ""}`} onClick={() => onChange(n)}>
            <img src={iconSrc(n)} alt="" width={48} height={48} draggable={false} />
          </button>
        ))}
      </div>
    </fieldset>
  );
}

const POS_KEYS = ["user_start", "zone_min", "zone_max", "opponent_start"] as const;
const PATH = { up: "M4 10l4-4 4 4", down: "M4 6l4 4 4-4", del: "M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" };
const Svg = ({ d }: { d: string }) => (
  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d={d} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
);
const OPT_PLACEHOLDER = ["Пункта нет, допработы оплачиваются отдельно", "Допработы за свой счёт, но не больше 5 рабочих дней",
  "Допработы за свой счёт без лимита", "Допработы за свой счёт и штраф 0,1 % в день"];

/** Перед сохранением: пустые варианты выкидываем, позиции сдвигаем вслед за текстом. */
function cleanZone(z: TargetZone): TargetZone {
  if (!z.options || !z.options.length) return { ...z, options: [] };
  const keep = z.options.map((o, i) => [o.trim(), i] as [string, number]).filter(([o]) => o);
  if (keep.length < 2) throw new Error("Добавьте хотя бы два варианта с текстом или переключите зону на «Числом»");
  const at = (v: number) => {
    const k = keep.findIndex(([, i]) => i === v);
    if (k < 0) throw new Error("Ваш старт, старт собеседника и края зоны должны указывать на варианты с текстом");
    return k;
  };
  const out: TargetZone = { ...z, options: keep.map(([o]) => o) };
  POS_KEYS.forEach((k) => { out[k] = at(z[k]); });
  return out;
}

/** Целевая зона: числом (четыре числа в одной единице) или шкалой вариантов (формулировки от лучшего для вас, позиции — номера). */
function ZoneField({ zone, onChange }: { zone: TargetZone; onChange: (z: TargetZone) => void }) {
  const [ord, setOrd] = useState(isOrdinal(zone));
  const opts = zone.options ?? [];
  const lbl = (k: string, label: string) => <FieldLabel label={label} help={FIELD_HELP[k]} />;
  const setNum = (k: string, v: string) => onChange({ ...zone, [k]: k === "unit" ? v : Number(v) });
  const remap = (f: (v: number) => number, options: string[]) => {
    const z: TargetZone = { ...zone, options };
    POS_KEYS.forEach((k) => { z[k] = f(zone[k]); });
    onChange(z);
  };
  const toOptions = () => {
    setOrd(true);
    if (!opts.length) onChange({ ...zone, options: ["", "", ""], user_start: 0, zone_min: 0, zone_max: 1, opponent_start: 2 });
  };
  const toNumbers = () => { setOrd(false); onChange({ ...zone, options: [] }); };
  const move = (i: number, j: number) => {
    const o = [...opts];
    [o[i], o[j]] = [o[j], o[i]];
    remap((v) => (v === i ? j : v === j ? i : v), o);
  };
  const remove = (i: number) => remap((v) => (v > i ? v - 1 : v === i ? Math.max(0, Math.min(i, opts.length - 2)) : v), opts.filter((_, k) => k !== i));
  const pick = (k: typeof POS_KEYS[number], label: string, help: string) => (
    <label>{lbl(help, label)}<select value={zone[k]} onChange={(e) => onChange({ ...zone, [k]: Number(e.target.value) })}>
      {opts.map((o, i) => <option key={i} value={i}>{i + 1}. {o.trim() || "(пусто)"}</option>)}
    </select></label>
  );
  return (
    <fieldset className="zone-field"><legend>Целевая зона соглашения</legend>
      <div className="zone-kind">
        <FieldLabel label="Как описать торг" help={FIELD_HELP.zone_kind} />
        <div className="tabs" role="group" aria-label="Вид целевой зоны">
          <button type="button" className={ord ? "" : "on"} aria-pressed={!ord} onClick={toNumbers}>Числом</button>
          <button type="button" className={ord ? "on" : ""} aria-pressed={ord} onClick={toOptions}>Вариантами</button>
        </div>
      </div>
      {!ord ? <>
        <label>{lbl("unit", "Предмет и единица торга через запятую")}<input value={zone.unit} placeholder="стоимость доработки, тыс. руб." onChange={(e) => setNum("unit", e.target.value)} /></label>
        <label>{lbl("user_start", "Ваша стартовая позиция")}<input type="number" value={zone.user_start} onChange={(e) => setNum("user_start", e.target.value)} /></label>
        <label>{lbl("zone_min", "Зона от")}<input type="number" value={zone.zone_min} onChange={(e) => setNum("zone_min", e.target.value)} /></label>
        <label>{lbl("zone_max", "Зона до")}<input type="number" value={zone.zone_max} onChange={(e) => setNum("zone_max", e.target.value)} /></label>
        <label>{lbl("opponent_start", "Старт собеседника")}<input type="number" value={zone.opponent_start} onChange={(e) => setNum("opponent_start", e.target.value)} /></label>
        <p className="muted small">Зона лежит между стартовыми позициями сторон и не касается старта собеседника. Пример: вы 29, зона 30–32, собеседник 35.</p>
      </> : <>
        <label>{lbl("subject_words", "Предмет торга")}<input value={zone.unit} placeholder="пункт о допработах при срыве срока" onChange={(e) => onChange({ ...zone, unit: e.target.value })} /></label>
        <div className="opt-list">
          <FieldLabel label="Варианты, от лучшего для вас к худшему" help={FIELD_HELP.options} />
          {opts.map((o, i) => (
            <div key={i} className="opt-row">
              <span className="opt-n num">{i + 1}</span>
              <input value={o} maxLength={200} aria-label={`Вариант ${i + 1}`} placeholder={OPT_PLACEHOLDER[i] ?? "Ещё один вариант условия"}
                onChange={(e) => onChange({ ...zone, options: opts.map((x, k) => (k === i ? e.target.value : x)) })} />
              <button type="button" className="opt-btn" disabled={i === 0} title="Выше" aria-label={`Поднять вариант ${i + 1}`} onClick={() => move(i, i - 1)}><Svg d={PATH.up} /></button>
              <button type="button" className="opt-btn" disabled={i === opts.length - 1} title="Ниже" aria-label={`Опустить вариант ${i + 1}`} onClick={() => move(i, i + 1)}><Svg d={PATH.down} /></button>
              <button type="button" className="opt-btn" disabled={opts.length <= 2} title="Удалить" aria-label={`Удалить вариант ${i + 1}`} onClick={() => remove(i)}><Svg d={PATH.del} /></button>
            </div>
          ))}
          {opts.length < 8 && <button type="button" className="add" onClick={() => onChange({ ...zone, options: [...opts, ""] })}>Добавить вариант</button>}
        </div>
        <div className="opt-picks">
          {pick("user_start", "Ваш старт", "opt_user_start")}
          {pick("opponent_start", "Старт собеседника", "opt_opponent_start")}
          {pick("zone_min", "Зона от", "opt_zone")}
          {pick("zone_max", "Зона до", "opt_zone")}
        </div>
        <p className="muted small">Сверху лучший для вас вариант. Ваш старт стоит в списке выше старта собеседника, зона между ними. Пример: вы с 1, зона 1–2, собеседник с 4.</p>
      </>}
    </fieldset>
  );
}

function lines(v: string) { return v.split("\n").map((x) => x.trim()).filter(Boolean); }

function Setup({ scenario, copy, go }: { scenario?: Scenario; copy?: boolean; go: Go }) {
  const [card, setCard] = useState<ScenarioCard>(scenario ? (copy ? { ...scenario, name: `${scenario.name} (копия)`, locked_by_org: false } : scenario) : EMPTY);
  const [brief, setBrief] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [help, setHelp] = useState(false);
  const [genKey, setGenKey] = useState(0);
  const [token, setToken] = useState(store.get("arena.adminToken") ?? "");
  const set = (k: keyof ScenarioCard, v: unknown) => setCard({ ...card, [k]: v });
  const saveToken = (v: string) => { setToken(v); store.set("arena.adminToken", v.trim() || null); };
  const save = async () => {
    setErr("");
    try {
      const clean = { ...card, target_zone: cleanZone(card.target_zone), coach_tips: (card.coach_tips ?? []).map((t) => t.trim()).filter(Boolean),
        hints: (card.hints ?? []).filter((h) => h.text.trim()) };
      const s = scenario && !copy ? await api.updateScenario(scenario.id, clean) : await api.createScenario(clean);
      await startScenario(s.id, go, setErr);
    } catch (e) { setErr((e as Error).message); }
  };
  const gen = async () => {
    setErr(""); setBusy(true);
    try { const g = await api.generate(brief); setCard({ ...g, coach_tips: card.coach_tips, hints: card.hints }); setGenKey((k) => k + 1); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const lbl = (k: string, label: string) => <FieldLabel label={label} help={FIELD_HELP[k]} />;
  const text = (k: keyof ScenarioCard, label: string, area = false) => (
    <label>{lbl(k, label)}{area
      ? <textarea value={card[k] as string} onChange={(e) => set(k, e.target.value)} />
      : <input value={card[k] as string} onChange={(e) => set(k, e.target.value)} />}</label>
  );
  const select = (k: keyof ScenarioCard, label: string, opts: [string, string][]) => (
    <label>{lbl(k, label)}<select value={card[k] as string} onChange={(e) => set(k, e.target.value)}>{opts.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>
  );
  return (
    <main className="form">
      <section className="gen">
        <div className="gen-h">
          <label htmlFor="brief">Опишите ситуацию, и карточка соберётся сама</label>
          <button type="button" className="ghost helpbtn" onClick={() => setHelp(true)}><Icon name="book" size={16} />Как заполнить сценарий</button>
        </div>
        <p className="small muted gen-sub">{FIELD_HELP.brief}</p>
        <textarea id="brief" placeholder="Снимаю однушку два года за 28 тысяч. Хозяйка хочет 35, похожие квартиры рядом стоят 32–34. Готов на 30–31, максимум 32. Если не договоримся, перееду, это ещё 15 тысяч." value={brief} onChange={(e) => setBrief(e.target.value)} />
        <div className="gen-foot">
          <button onClick={gen} disabled={busy || brief.trim().length < 10}>{busy ? "Собираем карточку…" : "Сгенерировать карточку"}</button>
          <span className="small muted">Проверьте поля после генерации: модель может ошибиться в числах.</span>
        </div>
      </section>
      {help && <ScenarioHelp onClose={() => setHelp(false)} />}
      {text("name", "Название")}{text("domain", "Сфера")}
      <IconPicker domain={card.domain} value={card.domain_icon ?? null} onChange={(v) => set("domain_icon", v)} />
      {text("topic", "Тема")}
      {select("difficulty", "Сложность", [["easy", "Лёгкая"], ["medium", "Средняя"], ["hard", "Сложная"]])}
      {select("tone", "Тон", [["neutral", "Нейтральный"], ["friendly", "Дружелюбный"], ["strict", "Строгий"], ["skeptical", "Скептичный"]])}
      {select("method", "Метод, который тренируем", [["free", "Свободный"], ["spin", "SPIN"], ["harvard", "Гарвардский"], ["batna", "BATNA"]])}
      {select("style", "Стиль собеседника", [["hard", "Жёсткий"], ["cooperative", "Сотрудничающий"], ["avoiding", "Уклоняющийся"], ["pressing", "Давящий"], ["emotional", "Эмоциональный"]])}
      {text("user_role", "Ваша роль")}{text("user_goal", "Ваша цель", true)}
      {text("opponent_role", "Роль собеседника")}
      <label>{lbl("opponent_name", "Имя собеседника")}<input value={card.opponent_name ?? ""} maxLength={80} placeholder="Вымышленные имя и фамилия; если пусто, в диалоге будет роль" onChange={(e) => set("opponent_name", e.target.value)} /></label>
      {text("opponent_goal", "Цель собеседника", true)}
      <label>{lbl("opponent_hidden_interests", "Скрытые интересы собеседника (по строке)")}<textarea value={card.opponent_hidden_interests.join("\n")} onChange={(e) => set("opponent_hidden_interests", lines(e.target.value))} /></label>
      {text("opponent_batna", "BATNA собеседника")}{text("user_batna", "Ваша BATNA")}
      <ZoneField key={`${scenario?.id ?? "new"}-${genKey}`} zone={card.target_zone} onChange={(z) => set("target_zone", z)} />
      <label>{lbl("mandatory_details", "Обязательные детали (по строке)")}<textarea value={card.mandatory_details.join("\n")} onChange={(e) => set("mandatory_details", lines(e.target.value))} /></label>
      {text("context", "Контекст", true)}
      <label>{lbl("opening", "Первая реплика собеседника")}<textarea value={card.opening ?? ""} placeholder="Если пусто, собеседник начнёт сам: с сути вопроса и своей стартовой позиции"
        onChange={(e) => set("opening", e.target.value)} /></label>
      {select("voice", "Голос собеседника в режиме «3D и голос»", [["female", "Женский"], ["male", "Мужской"]])}
      <AvatarField value={card.avatar_url} onChange={(v, voice) => setCard({ ...card, avatar_url: v, ...(voice ? { voice } : {}) })} />
      <label>Наставления перед стартом (по строке)<textarea value={(card.coach_tips ?? []).join("\n")} placeholder="Маскот покажет их до первого хода, перед стандартными советами по методу"
        onChange={(e) => set("coach_tips", e.target.value.split("\n"))} /></label>
      <HintsField value={card.hints ?? []} maxTurns={card.max_turns} onChange={(v) => set("hints", v)} />
      <label>{lbl("max_turns", "Лимит ходов")}<input type="number" value={card.max_turns} onChange={(e) => set("max_turns", Number(e.target.value))} /></label>
      <label className="check"><input type="checkbox" checked={card.locked_by_org} onChange={(e) => set("locked_by_org", e.target.checked)} />Зафиксировать для сотрудников организации</label>
      <label>Токен администратора (запасной способ; администратор организации фиксирует и меняет сценарии своей организации без токена)<input type="password" value={token} onChange={(e) => saveToken(e.target.value)} /></label>
      {err && <p className="error">{err}</p>}
      <button className="primary" onClick={save}>Сохранить и начать</button>
    </main>
  );
}

function History({ go }: { go: Go }) {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.history().then(setItems).catch((e) => setErr(`История не загрузилась: ${e.message}`)); }, []);
  const done = (items ?? []).filter((h) => h.status === "finished");
  const inZone = done.filter((h) => h.outcome === "agreement_in_zone").length;
  const scores = done.map((h) => h.score).filter((x): x is number => x != null);
  const best = scores.length ? Math.round(Math.max(...scores)) : null;
  return (
    <main className="flush">
      <Scene art={ART.folders}>
        <span className="caps">Ваши переговоры</span>
        <h1>История сессий</h1>
        {items && items.length > 0
          ? <div className="facts">
            <div className="fact"><span className="num">{items.length}</span><span className="caps">{plural(items.length, "сессия", "сессии", "сессий")}</span></div>
            <div className="fact"><span className="num">{inZone}</span><span className="caps">{plural(inZone, "соглашение", "соглашения", "соглашений")} в целевой зоне</span></div>
            {best !== null && <div className="fact"><span className="num">{best}</span><span className="caps">лучший балл</span></div>}
          </div>
          : <p className="lead">Здесь собираются все сессии: незавершённые можно продолжить, по завершённым открыть разбор.</p>}
      </Scene>
      <div className="body">
        {err && <p className="error">{err}</p>}
        {items && !items.length && (
          <Empty art={ART.coffee} title="Сессий пока нет">
            <p>Начните любой сценарий, и он появится здесь вместе с разбором.</p>
            <button className="primary" onClick={() => go({ name: "list" })}>К сценариям<Icon name="arrow" size={16} /></button>
          </Empty>
        )}
        {items && items.length > 0 && <div className="card sessions">{items.map((s) => <SessionRow key={s.id} h={s} go={go} />)}</div>}
      </div>
    </main>
  );
}

// Все варианты звучат разумно: различаются техникой, а не вежливостью. 2 — лучший ход, 1 — частый ход с изъяном, 0 — ход, который ухудшает позицию.
// Порядок вариантов перемешивается при каждом прохождении.
const QUIZ: { q: string; a: [string, number, Weak | null][] }[] = [
  { q: "Руководитель: «Отчёт нужен к пятнице, клиент ждёт». Без данных соседнего отдела вы к пятнице не успеете. Первый ход?", a: [
    ["Предупреждаю, что к пятнице не успеваю, и предлагаю перенести на понедельник", 1, "interests"],
    ["Уточняю, какую часть клиент должен увидеть в пятницу, а что можно донести позже", 2, null],
    ["Беру срок и договариваюсь с соседним отделом, чтобы данные дали раньше", 0, "offers"],
    ["Прошу выделить мне помощника, чтобы успеть к пятнице", 1, "interests"],
  ] },
  { q: "Заказчик: «Конкурент делает то же самое на 20% дешевле». Ваш ответ?", a: [
    ["Спрашиваю, что именно входит в предложение конкурента и на каких условиях", 2, null],
    ["Объясняю, чем наше решение лучше, и сохраняю цену", 1, "interests"],
    ["Предлагаю скидку 10%, чтобы встретиться посередине", 0, "offers"],
    ["Предлагаю ту же цену при сокращённом объёме работ", 1, "interests"],
  ] },
  { q: "Коллега из соседнего отдела отказывается брать половину общей задачи: «У нас и так завал». Что делаете?", a: [
    ["Предлагаю поделить поровну: так будет честно для обоих отделов", 1, "criteria"],
    ["Выясняю, что у них горит сейчас, и предлагаю взять часть их работы в обмен", 2, null],
    ["Выношу вопрос на руководителя, пусть распределит", 0, "interests"],
    ["Беру задачу целиком: отношения с отделом важнее", 0, "offers"],
  ] },
  { q: "Собеседник резко: «Вы вообще понимаете, о чём говорите?» Ваша реакция?", a: [
    ["Спокойно уточняю, какой пункт вызвал сомнение", 2, null],
    ["Привожу три аргумента, почему моё предложение верное", 1, "emotions"],
    ["Говорю, что в таком тоне разговор не продолжу", 1, "emotions"],
    ["Извиняюсь и предлагаю пересмотреть условия", 0, "offers"],
  ] },
  { q: "Вы назвали 500 тыс. ₽ за проект, заказчик — 300 тыс. Как обоснуете свою цифру?", a: [
    ["Показываю расчёт: трудозатраты команды по этапам и рыночные ставки на такие работы", 2, null],
    ["Говорю, что это стандартная цена для проектов такого масштаба", 1, "criteria"],
    ["Сразу предлагаю 400 тыс., чтобы быстрее договориться", 0, "offers"],
    ["Ссылаюсь на то, что прошлый клиент заплатил столько же", 1, "criteria"],
  ] },
  { q: "Вы готовы уступить заказчику 5% цены. Как лучше это сделать?", a: [
    ["Уступаю сразу, чтобы показать добрую волю", 0, "offers"],
    ["Уступаю, если заказчик подписывает договор на год вместо квартала", 2, null],
    ["Беру паузу до завтра и возвращаюсь с уступкой", 1, "offers"],
    ["Предлагаю скидку при условии, что он согласится прямо сейчас", 1, "emotions"],
  ] },
  { q: "Поставщик поднимает цену на 10%. У вас есть другой поставщик с ростом 4%, но переход займёт месяц. Что делаете?", a: [
    ["Сразу говорю, что уйдём к другому, если цену не снизят", 0, "emotions"],
    ["Сравниваю его условия со своей альтернативой с учётом месяца на переход и называю, какой рост для нас приемлем", 2, null],
    ["Соглашаюсь на 10%: переход слишком рискованный", 0, "batna"],
    ["Прошу снизить рост до 4%, как у другого поставщика", 1, "batna"],
  ] },
  { q: "Третий ход подряд собеседник не двигается, а его условия уже хуже вашей альтернативы. Что делаете?", a: [
    ["Уступаю ещё, чтобы не потерять сделку", 0, "batna"],
    ["Спокойно завершаю переговоры и выбираю альтернативу", 2, null],
    ["Ставлю срок: решение нужно до конца дня", 1, "emotions"],
    ["Предлагаю перерыв и возвращаюсь с новым вариантом условий", 1, "batna"],
  ] },
];

function shuffled<T>(xs: T[]): T[] {
  const a = [...xs];
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

const KEYS = ["1", "2", "3", "4"];

function EntryTest({ go }: { go: Go }) {
  const [answers, setAnswers] = useState<[string, number, Weak | null][]>([]);
  const [order, setOrder] = useState(() => QUIZ.map((x) => shuffled(x.a)));
  const [items, setItems] = useState<Scenario[]>([]);
  useEffect(() => { api.scenarios().then(setItems).catch(() => undefined); }, []);
  const n = answers.length;
  useEffect(() => {
    if (n >= QUIZ.length) return;
    const onKey = (e: KeyboardEvent) => {
      const i = KEYS.indexOf(e.key);
      if (i >= 0 && order[n][i]) setAnswers((a) => (a.length === n ? [...a, order[n][i]] : a));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [n, order]);
  const skip = () => { store.set(TEST_KEY, "skipped"); go({ name: "list" }); };
  if (n < QUIZ.length) {
    const { q } = QUIZ[n];
    return (
      <main className="quiz">
        <div className="qhead"><span className="segs">{QUIZ.map((_, i) => <i key={i} className={i <= n ? "on" : ""} />)}</span><span className="cap num">Вопрос {n + 1} из {QUIZ.length}</span></div>
        <p className="cap">Входной тест: подберём сложность и первый сценарий.</p>
        <h1>{q}</h1>
        {order[n].map((opt, i) => <button key={i} className="opt" onClick={() => setAnswers([...answers, opt])}><kbd>{KEYS[i]}</kbd><span>{opt[0]}</span></button>)}
        <button className="link" onClick={skip}>Пропустить тест</button>
      </main>
    );
  }
  const score = answers.reduce((sum, [, p]) => sum + p, 0);
  const level = score <= 7 ? "easy" : score <= 12 ? "medium" : "hard";
  const counts = answers.reduce((c, [, , w]) => (w ? { ...c, [w]: (c[w] ?? 0) + 1 } : c), {} as Partial<Record<Weak, number>>);
  const weak = (Object.keys(counts) as Weak[]).sort((x, y) => (counts[y] ?? 0) - (counts[x] ?? 0))[0];
  const rec = recommend(items, level, weak ?? null);
  store.set(TEST_KEY, JSON.stringify({ level, weak: weak ?? null }));
  return (
    <main className="quiz">
      <span className="caps">Результат входного теста</span>
      <h1>Рекомендуемая сложность: {RU[level]}</h1>
      <p>{weak ? <>Слабее всего: <b>{WEAK_RU[weak]}</b>.</> : "Явно слабых сторон тест не показал."}</p>
      {rec && <p>Начните со сценария «{rec.name}» ({RU[rec.difficulty]}, метод {RU[rec.method]}).</p>}
      <div className="row">
        {rec && <button className="primary" onClick={() => startScenario(rec.id, go, () => go({ name: "list" }))}>Начать<Icon name="arrow" size={16} /></button>}
        <button onClick={() => go({ name: "list" })}>К сценариям</button>
        <button className="ghost" onClick={() => { setAnswers([]); setOrder(QUIZ.map((x) => shuffled(x.a))); }}>Пройти заново</button>
      </div>
    </main>
  );
}
