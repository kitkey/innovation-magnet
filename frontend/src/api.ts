export type TargetZone = { unit: string; user_start: number; zone_min: number; zone_max: number; opponent_start: number };

export type ScenarioCard = {
  name: string;
  domain: string;
  topic: string;
  difficulty: "easy" | "medium" | "hard";
  tone: "neutral" | "friendly" | "strict" | "skeptical";
  method: "spin" | "harvard" | "batna" | "free";
  style: "hard" | "cooperative" | "avoiding" | "pressing" | "emotional";
  user_role: string;
  user_goal: string;
  opponent_role: string;
  opponent_goal: string;
  opponent_hidden_interests: string[];
  opponent_batna: string;
  user_batna: string;
  target_zone: TargetZone;
  mandatory_details: string[];
  context: string;
  max_turns: number;
  locked_by_org: boolean;
  voice: "female" | "male";
  avatar_url: string | null;
};

export type Scenario = ScenarioCard & { id: string; org_id: string | null; builtin: boolean; can_edit: boolean; edit_key?: string | null };

export type User = { id: string; login: string; display_name: string; role: "member" | "org_admin"; org_id: string | null; org_name: string | null; public_in_leaderboard: boolean };
export type Org = { id: string; name: string; invite_code: string | null };
export type Period = "week" | "month" | "all";
export type MemberStats = {
  id: string; login: string; display_name: string; role: User["role"]; sessions: number; training_minutes: number;
  axes: Record<string, number>; in_zone_share: number | null; rating: number | null;
};
export type Board = { scope: "org" | "global"; period: Period; top_n: number; rows: { display_name: string; org_name: string | null; rating: number; sessions: number; me: boolean }[] };

export type TurnOut = {
  turn: number;
  opponent_message: string;
  status: "active" | "finished";
  outcome: string | null;
  analysis: { labels: string[]; mentioned_details: string[]; proposed_value: number | null };
  state: { trust: number; readiness: number; irritation: number; position: number };
  mood: Mood;
};

export type Mood = "neutral" | "happy" | "angry" | "sad" | "disgust";
export type VoiceTurnOut = TurnOut & { recognized: string; audio_url: string | null };
export type VoiceStatus = { stt: boolean; tts: boolean; provider: string | null; ffmpeg: boolean; max_seconds: number; avatar_max_mb: number };
export type Speech = { audio: string | null; mime: string; words: string[]; wtimes: number[]; wdurations: number[]; mood: Mood; voice?: string; role?: string };
export type AvatarUpload = { url: string; size: number; morph_targets: number; visemes: number; warnings: string[] };

export type SessionResult = {
  session_id: string;
  status: string;
  outcome: string | null;
  incomplete: boolean;
  final_position: number | null;
  in_zone: boolean | null;
  position_shift: number | null;
  walk_away_justified?: boolean | null;
  walk_away_note?: string | null;
  details_covered: string[];
  details_missed: string[];
  judge: { axes: Record<string, number>; key_moments: { quote: string; problem: string; better: string }[]; next_scenario_hint: string } | null;
  judge_source: "llm" | "rules" | null;
};

export type Message = { role: "user" | "opponent"; text: string; labels: string[]; audio_url?: string | null; pending?: boolean };

export type SessionView = {
  id: string;
  scenario_id: string;
  card: ScenarioCard;
  status: "active" | "finished";
  outcome: string | null;
  turn: number;
  max_turns: number;
  state: TurnOut["state"];
  thresholds: { concede: number; breakdown_irritation: number; breakdown_trust: number };
  mood: Mood;
  messages: Message[];
};

export const store = {
  get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string | null) => { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* приватный режим */ } },
};

export const AUTH_KEY = "arena.authToken";
export const MODE_KEY = "arena.opponentMode";
const EDIT_KEYS = "arena.scenarioKeys";
const GUEST_SESSIONS = "arena.guestSessions";

function readJson<T>(k: string, fallback: T): T {
  try { return JSON.parse(store.get(k) ?? "") as T; } catch { return fallback; }
}

/** Ключи правки сценариев, созданных без входа: сервер выдаёт ключ один раз, браузер его хранит. */
export const editKeys = {
  all: () => readJson<Record<string, string>>(EDIT_KEYS, {}),
  add: (id: string, key: string) => store.set(EDIT_KEYS, JSON.stringify({ ...editKeys.all(), [id]: key })),
};

/** Гостевые сессии: общего списка на сервере нет, история гостя — это id, которые помнит его браузер. */
const guestSessions = {
  all: () => readJson<string[]>(GUEST_SESSIONS, []),
  add: (id: string) => { if (!store.get(AUTH_KEY)) store.set(GUEST_SESSIONS, JSON.stringify([id, ...guestSessions.all().filter((x) => x !== id)].slice(0, 50))); },
};

async function call<T>(path: string, init?: RequestInit, json = true): Promise<T> {
  const token = store.get("arena.adminToken");
  const auth = store.get(AUTH_KEY);
  const headers = { ...(json ? { "Content-Type": "application/json" } : {}), ...(token ? { "X-Admin-Token": token } : {}), ...(auth ? { Authorization: `Bearer ${auth}` } : {}), ...(init?.headers as Record<string, string> | undefined) };
  const r = await fetch(path, { ...init, headers });
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail;
    throw new Error(Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail ?? r.statusText);
  }
  return r.json();
}

export const api = {
  scenarios: () => call<Scenario[]>(store.get(AUTH_KEY) ? "/api/scenarios" : `/api/scenarios?ids=${Object.keys(editKeys.all()).join(",")}`),
  createScenario: async (card: ScenarioCard) => {
    const s = await call<Scenario>("/api/scenarios", { method: "POST", body: JSON.stringify(card) });
    if (s.edit_key) editKeys.add(s.id, s.edit_key);
    return s;
  },
  updateScenario: (id: string, card: ScenarioCard) => {
    const key = editKeys.all()[id];
    return call<Scenario>(`/api/scenarios/${id}`, { method: "PUT", body: JSON.stringify(card), headers: key ? { "X-Edit-Key": key } : {} });
  },
  generate: (description: string) => call<ScenarioCard>("/api/scenarios/generate", { method: "POST", body: JSON.stringify({ description }) }),
  start: async (id: string) => {
    const r = await call<{ session_id: string; opening: string; max_turns: number }>(`/api/sessions?scenario_id=${id}`, { method: "POST" });
    guestSessions.add(r.session_id);
    return r;
  },
  turn: (sid: string, message: string) => call<TurnOut>(`/api/sessions/${sid}/turn`, { method: "POST", body: JSON.stringify({ message }) }),
  finish: (sid: string) => call<{ ok: boolean }>(`/api/sessions/${sid}/finish`, { method: "POST" }),
  result: (sid: string) => call<SessionResult>(`/api/sessions/${sid}/result`),
  session: (sid: string) => call<SessionView>(`/api/sessions/${sid}`),
  rewind: async (sid: string, turn: number) => {
    const v = await call<SessionView>(`/api/sessions/${sid}/rewind`, { method: "POST", body: JSON.stringify({ turn }) });
    guestSessions.add(v.id);
    return v;
  },
  history: () => call<{ id: string; scenario: string; status: string; outcome: string | null; turns: number }[]>(store.get(AUTH_KEY) ? "/api/sessions" : `/api/sessions?ids=${guestSessions.all().join(",")}`),
  register: (login: string, password: string, display_name: string) => call<{ token: string; user: User }>("/api/auth/register", { method: "POST", body: JSON.stringify({ login, password, display_name }) }),
  login: (login: string, password: string) => call<{ token: string; user: User }>("/api/auth/login", { method: "POST", body: JSON.stringify({ login, password }) }),
  logout: () => call<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  me: () => call<User>("/api/auth/me"),
  updateProfile: (p: { display_name?: string; public_in_leaderboard?: boolean }) => call<User>("/api/profile", { method: "PATCH", body: JSON.stringify(p) }),
  createOrg: (name: string) => call<Org>("/api/orgs", { method: "POST", body: JSON.stringify({ name }) }),
  joinOrg: (code: string) => call<Org>("/api/orgs/join", { method: "POST", body: JSON.stringify({ code }) }),
  newInvite: () => call<Org>("/api/orgs/me/invite", { method: "POST" }),
  setMemberRole: (id: string, role: User["role"]) => call<{ id: string; role: User["role"] }>(`/api/orgs/me/members/${id}`, { method: "PATCH", body: JSON.stringify({ role }) }),
  removeMember: (id: string) => call<{ ok: boolean }>(`/api/orgs/me/members/${id}`, { method: "DELETE" }),
  leaveOrg: () => call<User>("/api/orgs/me/leave", { method: "POST" }),
  orgStats: (period: Period) => call<{ org: Org; period: Period; members: MemberStats[] }>(`/api/orgs/me/stats?period=${period}`),
  voiceTurn: (sid: string, audio: Blob, name: string) => { const f = new FormData(); f.append("audio", audio, name); return call<VoiceTurnOut>(`/api/sessions/${sid}/voice`, { method: "POST", body: f }, false); },
  voiceStatus: () => call<VoiceStatus>("/api/voice/status"),
  tts: (text: string, emotion: Mood, voice: ScenarioCard["voice"]) => call<Speech>("/api/tts", { method: "POST", body: JSON.stringify({ text, emotion, voice }) }),
  uploadAvatar: (file: File) => { const f = new FormData(); f.append("file", file, file.name); return call<AvatarUpload>("/api/avatars", { method: "POST", body: f }, false); },
  leaderboard: (scope: "org" | "global", period: Period) => call<Board>(`/api/leaderboard?scope=${scope}&period=${period}`),
};
