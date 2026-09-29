import { useEffect, useState } from "react";
import { ART, Empty, Scene } from "./art";
import { Icon } from "./icons";
import { api, AUTH_KEY, Board, MemberStats, MODE_KEY, Org, Period, Season, store, User } from "./api";
import { fmtDate, MedalDot, MedalTally, MEDAL_RU, ProfileMedals, ruleText, SeasonPanel, seasonTitle } from "./medals";

export type SetUser = (u: User | null) => void;

const PERIOD_RU: [Period, string][] = [["week", "Неделя"], ["month", "Месяц"], ["all", "Всё время"]];
const PERIOD_SEASON_RU: [Period, string][] = [["week", "Неделя"], ["month", "Месяц"], ["all", "Весь сезон"]];
const ROLE_RU: Record<User["role"], string> = { member: "участник", org_admin: "администратор" };

export function UserIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" />
    </svg>
  );
}

function Tabs<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return <div className="tabs">{options.map(([v, t]) => <button key={v} className={v === value ? "on" : ""} onClick={() => onChange(v)}>{t}</button>)}</div>;
}

const pct = (x: number | null) => (x === null ? "—" : `${Math.round(x * 100)}%`);
const num = (x: number | null) => (x === null ? "—" : x.toLocaleString("ru-RU", { maximumFractionDigits: 1 }));
const initialsOf = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("");
function plural(n: number, [one, few, many]: [string, string, string]) {
  const a = Math.abs(n) % 100, b = a % 10;
  return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many;
}

export function Auth({ onUser }: { onUser: SetUser }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setErr(""); setBusy(true);
    try {
      const r = mode === "login" ? await api.login(login, password) : await api.register(login, password, name);
      store.set(AUTH_KEY, r.token);
      onUser(r.user);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <main className="flush">
      <Scene art={ART.key}>
        <span className="caps">Аккаунт</span>
        <h1>{mode === "login" ? "Вход" : "Регистрация"}</h1>
        <p className="lead">С аккаунтом сессии попадают в лидерборд и кабинет организации.</p>
      </Scene>
      <div className="body">
        <section className="card form narrow">
      <Tabs value={mode} options={[["login", "Вход"], ["register", "Регистрация"]]} onChange={(m) => { setMode(m); setErr(""); }} />
      <label>Логин<input value={login} autoComplete="username" onChange={(e) => setLogin(e.target.value)} /></label>
      {mode === "register" && <label>Имя в лидерборде<input value={name} onChange={(e) => setName(e.target.value)} /></label>}
      <label>Пароль<input type="password" value={password} autoComplete={mode === "login" ? "current-password" : "new-password"} onChange={(e) => setPassword(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); }} /></label>
      {mode === "register" && <p className="small muted">Логин: латиница, цифры, точка, дефис, от 3 символов. Пароль от 6 символов.</p>}
      {err && <p className="error">{err}</p>}
      <button className="primary" disabled={busy || !login || !password} onClick={submit}>{mode === "login" ? "Войти" : "Зарегистрироваться"}</button>
      <p className="small muted">Без входа тренажёр работает в гостевом режиме: сессии не попадают в лидерборд и кабинет организации.</p>
        </section>
      </div>
    </main>
  );
}

export function Profile({ user, onUser }: { user: User; onUser: SetUser }) {
  const [name, setName] = useState(user.display_name);
  const [code, setCode] = useState("");
  const [orgName, setOrgName] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [mode, setMode] = useState<"text" | "avatar">(store.get(MODE_KEY) === "avatar" ? "avatar" : "text");
  const run = async (f: () => Promise<unknown>, ok: string) => {
    setErr(""); setMsg("");
    try { await f(); onUser(await api.me()); setMsg(ok); } catch (e) { setErr((e as Error).message); }
  };
  const logout = async () => {
    await api.logout().catch(() => undefined);
    store.set(AUTH_KEY, null); store.set("arena.activeSid", null);
    onUser(null);
  };
  return (
    <main className="flush">
      <Scene art={ART.key}>
        <span className="caps">Профиль</span>
        <h1>{user.display_name}</h1>
        <p className="lead">Логин {user.login}{user.org_id ? ` · ${user.org_name}, ${ROLE_RU[user.role]}` : " · без организации"}</p>
      </Scene>
      <div className="body grid2">
        <div className="col">
          <section className="card form">
            <h3>Имя и видимость</h3>
            <label>Имя в лидерборде<div className="row nowrap"><input value={name} onChange={(e) => setName(e.target.value)} />
              <button disabled={!name.trim() || name === user.display_name} onClick={() => run(() => api.updateProfile({ display_name: name }), "Имя сохранено")}>Сохранить</button></div></label>
            <label className="check"><input type="checkbox" checked={user.public_in_leaderboard}
              onChange={(e) => run(() => api.updateProfile({ public_in_leaderboard: e.target.checked }), "Настройка сохранена")} />Показывать меня в общем лидерборде</label>
          </section>
          <section className="card form">
            <h3>Собеседник по умолчанию</h3>
            <Tabs value={mode} options={[["text", "Текст"], ["avatar", "3D и голос"]]} onChange={(m) => { setMode(m); store.set(MODE_KEY, m); }} />
            <p className="small muted">В режиме «3D и голос» собеседник отвечает голосом и мимикой, текст ответа всё равно остаётся в чате. Переключается и в самом диалоге.</p>
          </section>
        </div>
        <div className="col">
          <section className="card form">
            <h3>Организация</h3>
            {user.org_id ? (
              <>
                <div className="orgline"><span className="ava sq">{initialsOf(user.org_name ?? "")}</span><div><b>{user.org_name}</b><span className="small muted">{ROLE_RU[user.role]}</span></div></div>
                <button onClick={() => { if (confirm(`Выйти из организации «${user.org_name}»? Вернуться можно по коду приглашения.`)) run(() => api.leaveOrg(), "Вы вышли из организации"); }}>Выйти из организации</button>
              </>
            ) : (
              <>
                <label>Код приглашения<div className="row nowrap"><input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Например, 3F9A1C0B" />
                  <button disabled={!code.trim()} onClick={() => run(() => api.joinOrg(code), "Вы вступили в организацию")}>Вступить</button></div></label>
                <label>Или создайте свою<div className="row nowrap"><input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Название организации" />
                  <button disabled={orgName.trim().length < 2} onClick={() => run(() => api.createOrg(orgName), "Организация создана, вы её администратор")}>Создать</button></div></label>
              </>
            )}
          </section>
          <ProfileMedals />
          {msg && <p className="note">{msg}</p>}
          {err && <p className="error">{err}</p>}
          <button className="logout" onClick={logout}><Icon name="back" size={16} />Выйти из аккаунта</button>
        </div>
      </div>
    </main>
  );
}

function leaders(members: MemberStats[]) {
  const best: [string, string, number][] = [];
  const top = members.filter((m) => m.rating !== null).sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0))[0];
  if (top) best.push(["Общий рейтинг", top.display_name, top.rating ?? 0]);
  const axes = [...new Set(members.flatMap((m) => Object.keys(m.axes)))];
  for (const a of axes) {
    const m = members.filter((x) => a in x.axes).sort((x, y) => y.axes[a] - x.axes[a])[0];
    if (m) best.push([a, m.display_name, m.axes[a]]);
  }
  return best;
}

export function OrgCabinet({ user, onUser }: { user: User; onUser: (u: User) => void }) {
  const [period, setPeriod] = useState<Period>("month");
  const [data, setData] = useState<{ org: Org; season: Season; members: MemberStats[] } | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const load = () => api.orgStats(period).then(setData).catch((e) => setErr(`Кабинет не загрузился: ${e.message}`));
  useEffect(() => { setErr(""); load(); }, [period]);
  const act = async (id: string, f: () => Promise<unknown>) => {
    setErr(""); setBusy(id);
    try {
      await f();
      if (id === user.id) { onUser(await api.me()); return; }
      await load();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };
  const regen = async () => { try { const org = await api.newInvite(); if (data) setData({ ...data, org }); } catch (e) { setErr((e as Error).message); } };
  if (!data) return <main>{err ? <p className="error">{err}</p> : <p className="muted">Загрузка…</p>}</main>;
  const best = leaders(data.members);
  const max = Math.max(1, ...data.members.map((m) => m.sessions));
  return (
    <main className="flush">
      <Scene art={ART.team}>
        <span className="caps">Кабинет организации</span>
        <h1>{data.org.name}</h1>
        <div className="facts">
          <div className="fact"><span className="num">{data.members.length}</span><span className="caps">{plural(data.members.length, ["участник", "участника", "участников"])}</span></div>
          <div className="fact"><span className="num">{data.members.reduce((a, m) => a + m.sessions, 0)}</span><span className="caps">сессий за период</span></div>
          <div className="fact"><span className="num">{Math.round(data.members.reduce((a, m) => a + m.training_minutes, 0))}</span><span className="caps">минут тренировок</span></div>
        </div>
      </Scene>
      <div className="body grid2 org">
        <div className="col">
          <section className="card invite">
            <span className="caps">Код приглашения</span>
            <b className="code big">{data.org.invite_code}</b>
            <div className="row">
              <button onClick={() => navigator.clipboard?.writeText(data.org.invite_code ?? "")}><Icon name="copy" size={16} />Скопировать</button>
              <button className="ghost" onClick={regen}>Выпустить новый код</button>
            </div>
            <p className="small muted">Сотрудник вводит код в профиле. Старый код после выпуска нового перестаёт работать.</p>
          </section>
          {best.length > 0 && (
            <section className="card">
              <h3>Лучшие за период</h3>
              <ul className="plain bests">{best.map(([k, n, v]) => <li key={k}><span className="muted">{k}</span><b>{n}</b><span className="num">{num(v)}</span></li>)}</ul>
            </section>
          )}
          <SeasonPanel onChanged={load} />
        </div>
        <div className="col">
          <div className="toolbar">
            <h2>Участники</h2>
            <Tabs value={period} options={PERIOD_SEASON_RU} onChange={setPeriod} />
          </div>
          <p className="small muted">{seasonTitle(data.season.name)}, с {fmtDate(data.season.started_at)}</p>
          {err && <p className="error">{err}</p>}
          {data.members.length <= 1 && (
            <Empty art={ART.team} title="Пока вы здесь один">
              <p>Отправьте коллегам код приглашения: они введут его в профиле и появятся в этом списке со своей статистикой.</p>
            </Empty>
          )}
          <div className="members">{data.members.map((m) => (
            <article key={m.id} className="card member">
              <div className="mhead">
                <span className="ava">{initialsOf(m.display_name)}</span>
                <div><b>{m.display_name}</b><span className="small muted">{m.login}{m.role === "org_admin" ? " · администратор" : ""}</span></div>
                <span className="rating"><span className="num">{num(m.rating)}</span><span className="caps">рейтинг</span></span>
              </div>
              <div className="mstats">
                <span><b className="num">{m.sessions}</b>{plural(m.sessions, ["сессия", "сессии", "сессий"])}<i><i style={{ width: `${(m.sessions / max) * 100}%` }} /></i></span>
                <span><b className="num">{Math.round(m.training_minutes)}</b>минут</span>
                <span><b className="num">{pct(m.in_zone_share)}</b>в целевой зоне</span>
              </div>
              {Object.keys(m.axes).length > 0 && (
                <div className="maxes">{Object.entries(m.axes).map(([k, v]) => (
                  <div key={k} className="maxis"><span>{k}</span><span className="num">{Math.round(v)}</span><div className="track"><div className={`fill ${v < 40 ? "low" : ""}`} style={{ width: `${v}%` }} /></div></div>
                ))}</div>
              )}
              <div className="row macts">
                {m.role === "org_admin"
                  ? <button disabled={!!busy} onClick={() => act(m.id, () => api.setMemberRole(m.id, "member"))}>Снять администратора</button>
                  : <button disabled={!!busy} onClick={() => act(m.id, () => api.setMemberRole(m.id, "org_admin"))}>Сделать администратором</button>}
                {m.id !== user.id && <button className="ghost" disabled={!!busy} onClick={() => { if (confirm(`Удалить ${m.display_name} из организации? История сессий останется в профиле участника.`)) act(m.id, () => api.removeMember(m.id)); }}>Удалить</button>}
              </div>
            </article>
          ))}</div>
        </div>
      </div>
    </main>
  );
}

type Row = Board["rows"][number];

function Place({ r, i }: { r: Row; i: number }) {
  return <span className="place num">{i + 1}{r.medal && <MedalDot medal={r.medal} title={`${MEDAL_RU[r.medal]}, если закрыть сезон сейчас`} />}</span>;
}

export function Leaderboard({ user }: { user: User | null }) {
  const [scope, setScope] = useState<"org" | "global">(user?.org_id ? "org" : "global");
  const [period, setPeriod] = useState<Period>("month");
  const [board, setBoard] = useState<Board | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { setErr(""); setBoard(null); api.leaderboard(scope, period).then(setBoard).catch((e) => setErr(e.message)); }, [scope, period]);
  const rows = board?.rows ?? [];
  const top = rows.slice(0, 3);
  const me = rows.findIndex((r) => r.me);
  const sub = (r: Row) => (scope === "global" ? r.org_name ?? "без организации" : `${r.sessions} ${plural(r.sessions, ["сессия", "сессии", "сессий"])} с оценкой`);
  return (
    <main className="flush">
      <Scene art={ART.podium}>
        <span className="caps">{scope === "org" ? user?.org_name ?? "Организация" : "Все участники"}</span>
        <h1>Лидерборд</h1>
        <p className="lead">{scope === "org" && board?.season && board.medal_rule
          ? <>{seasonTitle(board.season.name)}, с {fmtDate(board.season.started_at)}. {ruleText(board.medal_rule)}</>
          : "Рейтинг по лучшим сессиям за период. В общем лидерборде только те, кто разрешил это в профиле."}</p>
        {me >= 0 && <p className="mine">Вы на <b className="num">{me + 1}</b> месте, рейтинг <b className="num">{num(rows[me].rating)}</b></p>}
      </Scene>
      <div className="body">
        <div className="toolbar">
          <Tabs value={scope} options={user?.org_id ? [["org", user.org_name ?? "Организация"], ["global", "Общий"]] : [["global", "Общий"]]} onChange={setScope} />
          <Tabs value={period} options={scope === "org" ? PERIOD_SEASON_RU : PERIOD_RU} onChange={setPeriod} />
        </div>
        {err && <p className="error">{err}</p>}
        {!board && !err && <p className="muted">Загрузка…</p>}
        {board && !rows.length && (
          <Empty art={ART.podium} title="За этот период оценённых сессий нет">
            <p>Завершите сессию с разбором, и рейтинг появится здесь. Или выберите период подлиннее.</p>
          </Empty>
        )}
        {top.length > 0 && (
          <div className="podium">{top.map((r, i) => (
            <article key={i} className={`card pod p${i + 1} ${r.medal ? `m-${r.medal}` : ""} ${r.me ? "me" : ""}`}>
              <div className="podtop"><Place r={r} i={i} /><span className="ava">{initialsOf(r.display_name)}</span></div>
              <b className="nm">{r.display_name}{r.me && <span className="you">вы</span>}</b>
              <span className="small muted">{sub(r)}</span>
              <div className="podfoot"><span className="score num">{num(r.rating)}</span><span className="caps">рейтинг</span><MedalTally counts={r.medals} /></div>
            </article>
          ))}</div>
        )}
        {rows.length > 3 && (
          <div className="card board">
            <div className="brow bh"><span>#</span><span>Участник</span><span>Рейтинг</span><span>Сессий</span></div>
            {rows.slice(3).map((r, k) => (
              <div key={k} className={`brow ${r.me ? "me" : ""}`}>
                <Place r={r} i={k + 3} />
                <span className="who2"><b>{r.display_name}{r.me && <span className="you">вы</span>}<MedalTally counts={r.medals} /></b>{scope === "global" && <span className="small muted">{r.org_name ?? "без организации"}</span>}</span>
                <span className="num sc">{num(r.rating)}</span>
                <span className="num muted">{r.sessions}</span>
              </div>
            ))}
          </div>
        )}
        <div className="rules">
          <Icon name="book" size={18} />
          <p className="small">Очко сессии: средняя оценка судьи по осям × сложность (лёгкая 0,8, средняя 1,0, сложная 1,25) + 10 за соглашение в целевой зоне.
            Рейтинг: среднее по {board?.top_n ?? 5} лучшим сессиям за период{scope === "org" ? " внутри сезона" : ""}.
            {scope === "org" && board?.medal_rule && board.medal_rule.slots > 0 && " Метка у места показывает, какую медаль участник получит, если сезон закроют сейчас."} Цифры у имени — медали за прошлые сезоны.</p>
        </div>
      </div>
    </main>
  );
}
