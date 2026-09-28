import { useEffect, useState } from "react";
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
    <main className="form narrow">
      <Tabs value={mode} options={[["login", "Вход"], ["register", "Регистрация"]]} onChange={(m) => { setMode(m); setErr(""); }} />
      <label>Логин<input value={login} autoComplete="username" onChange={(e) => setLogin(e.target.value)} /></label>
      {mode === "register" && <label>Имя в лидерборде<input value={name} onChange={(e) => setName(e.target.value)} /></label>}
      <label>Пароль<input type="password" value={password} autoComplete={mode === "login" ? "current-password" : "new-password"} onChange={(e) => setPassword(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); }} /></label>
      {mode === "register" && <p className="small muted">Логин: латиница, цифры, точка, дефис, от 3 символов. Пароль от 6 символов.</p>}
      {err && <p className="error">{err}</p>}
      <button className="primary" disabled={busy || !login || !password} onClick={submit}>{mode === "login" ? "Войти" : "Зарегистрироваться"}</button>
      <p className="small muted">Без входа тренажёр работает в гостевом режиме: сессии не попадают в лидерборд и кабинет организации.</p>
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
    <main className="form narrow">
      <h2>Профиль</h2>
      <p className="muted">Логин: {user.login}</p>
      <label>Имя<div className="row"><input value={name} onChange={(e) => setName(e.target.value)} />
        <button disabled={!name.trim() || name === user.display_name} onClick={() => run(() => api.updateProfile({ display_name: name }), "Имя сохранено")}>Сохранить</button></div></label>
      <label className="check"><input type="checkbox" checked={user.public_in_leaderboard}
        onChange={(e) => run(() => api.updateProfile({ public_in_leaderboard: e.target.checked }), "Настройка сохранена")} />Показывать меня в общем лидерборде</label>
      <label>Собеседник по умолчанию<Tabs value={mode} options={[["text", "Текст"], ["avatar", "3D и голос"]]}
        onChange={(m) => { setMode(m); store.set(MODE_KEY, m); }} /></label>
      <p className="small muted">В режиме «3D и голос» собеседник отвечает голосом и мимикой, текст ответа всё равно остаётся в чате. Переключается и в самом диалоге.</p>
      <section className="panel">
        <h3>Организация</h3>
        {user.org_id ? (
          <>
            <p>{user.org_name} · {ROLE_RU[user.role]}</p>
            <button onClick={() => { if (confirm(`Выйти из организации «${user.org_name}»? Вернуться можно по коду приглашения.`)) run(() => api.leaveOrg(), "Вы вышли из организации"); }}>Выйти из организации</button>
          </>
        ) : (
          <>
            <label>Код приглашения<div className="row"><input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Например, 3F9A1C0B" />
              <button disabled={!code.trim()} onClick={() => run(() => api.joinOrg(code), "Вы вступили в организацию")}>Вступить</button></div></label>
            <label>Или создайте свою<div className="row"><input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Название организации" />
              <button disabled={orgName.trim().length < 2} onClick={() => run(() => api.createOrg(orgName), "Организация создана, вы её администратор")}>Создать</button></div></label>
          </>
        )}
      </section>
      <ProfileMedals />
      {msg && <p className="note">{msg}</p>}
      {err && <p className="error">{err}</p>}
      <button className="link" onClick={logout}>Выйти</button>
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
  if (!data) return <main>{err ? <p className="error">{err}</p> : <p>Загрузка…</p>}</main>;
  const best = leaders(data.members);
  return (
    <main className="cabinet">
      <h2>{data.org.name}</h2>
      <section className="panel">
        <p>Код приглашения: <b className="code">{data.org.invite_code}</b></p>
        <div className="row">
          <button onClick={() => navigator.clipboard?.writeText(data.org.invite_code ?? "")}>Скопировать</button>
          <button onClick={regen}>Выпустить новый код</button>
        </div>
        <p className="small muted">Сотрудник вводит код в профиле. Старый код после выпуска нового перестаёт работать.</p>
      </section>
      <SeasonPanel onChanged={load} />
      <div className="row between">
        <Tabs value={period} options={PERIOD_SEASON_RU} onChange={setPeriod} />
        <span className="small muted">{seasonTitle(data.season.name)}, с {fmtDate(data.season.started_at)}</span>
      </div>
      {err && <p className="error">{err}</p>}
      {best.length > 0 && (
        <section className="panel">
          <h3>Лучшие за период</h3>
          <ul className="plain">{best.map(([k, n, v]) => <li key={k}><span className="muted">{k}:</span> {n} · {v}</li>)}</ul>
        </section>
      )}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Участник</th><th>Сессий</th><th>Минут</th><th>В зоне</th><th>Рейтинг</th><th>Средние оценки по осям</th><th>Права</th></tr></thead>
          <tbody>{data.members.map((m) => (
            <tr key={m.id}>
              <td>{m.display_name}<div className="small muted">{m.login}{m.role === "org_admin" ? " · администратор" : ""}</div></td>
              <td>{m.sessions}</td><td>{m.training_minutes}</td><td>{pct(m.in_zone_share)}</td><td>{m.rating ?? "—"}</td>
              <td className="small">{Object.entries(m.axes).map(([k, v]) => <div key={k}>{k}: {v}</div>)}{!Object.keys(m.axes).length && "—"}</td>
              <td className="small">
                <div className="row">
                  {m.role === "org_admin"
                    ? <button disabled={!!busy} onClick={() => act(m.id, () => api.setMemberRole(m.id, "member"))}>Снять администратора</button>
                    : <button disabled={!!busy} onClick={() => act(m.id, () => api.setMemberRole(m.id, "org_admin"))}>Сделать администратором</button>}
                  {m.id !== user.id && <button disabled={!!busy} onClick={() => { if (confirm(`Удалить ${m.display_name} из организации? История сессий останется в профиле участника.`)) act(m.id, () => api.removeMember(m.id)); }}>Удалить</button>}
                </div>
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </main>
  );
}

export function Leaderboard({ user }: { user: User | null }) {
  const [scope, setScope] = useState<"org" | "global">(user?.org_id ? "org" : "global");
  const [period, setPeriod] = useState<Period>("month");
  const [board, setBoard] = useState<Board | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { setErr(""); setBoard(null); api.leaderboard(scope, period).then(setBoard).catch((e) => setErr(e.message)); }, [scope, period]);
  return (
    <main className="cabinet">
      <h2>Лидерборд</h2>
      <div className="row between">
        <Tabs value={scope} options={user?.org_id ? [["org", user.org_name ?? "Организация"], ["global", "Общий"]] : [["global", "Общий"]]} onChange={setScope} />
        <Tabs value={period} options={scope === "org" ? PERIOD_SEASON_RU : PERIOD_RU} onChange={setPeriod} />
      </div>
      {scope === "org" && board?.season && board.medal_rule && (
        <p className="small muted">{seasonTitle(board.season.name)}, с {fmtDate(board.season.started_at)}. {ruleText(board.medal_rule)}
          {board.medal_rule.slots > 0 && " Метка у места показывает, какую медаль участник получит, если сезон закроют сейчас."}</p>
      )}
      {err && <p className="error">{err}</p>}
      {board && (board.rows.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Участник</th>{scope === "global" && <th>Организация</th>}<th>Рейтинг</th><th>Сессий с оценкой</th></tr></thead>
            <tbody>{board.rows.map((r, i) => (
              <tr key={i} className={r.me ? "me" : ""}>
                <td className="place">{i + 1}{r.medal && <MedalDot medal={r.medal} title={`${MEDAL_RU[r.medal]}, если закрыть сезон сейчас`} />}</td>
                <td>{r.display_name}<MedalTally counts={r.medals} /></td>{scope === "global" && <td>{r.org_name ?? "—"}</td>}<td>{r.rating}</td><td>{r.sessions}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <p className="muted">За этот период оценённых сессий нет.</p>)}
      <p className="small muted">Очко сессии: средняя оценка судьи по осям × сложность (лёгкая 0,8, средняя 1,0, сложная 1,25) + 10 за соглашение в целевой зоне.
        Рейтинг: среднее по {board?.top_n ?? 5} лучшим сессиям за период{scope === "org" ? " внутри сезона" : ""}. Цифры у имени — медали за прошлые сезоны. {scope === "global" && "В общем лидерборде только те, кто разрешил это в профиле."}</p>
    </main>
  );
}
