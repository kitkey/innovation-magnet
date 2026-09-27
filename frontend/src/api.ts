export type TargetZone = { unit: string; user_start: number; zone_min: number; zone_max: number; opponent_start: number };

export type ScenarioCard = {
  name: string;
  domain: string;
  topic: string;
  difficulty: "easy" | "medium" | "hard";
  tone: "neutral" | "friendly" | "strict" | "skeptical";
  method: "spin" | "harvard" | "free";
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
};

export type Scenario = ScenarioCard & { id: string };

export type TurnOut = {
  turn: number;
  opponent_message: string;
  status: "active" | "finished";
  outcome: string | null;
  analysis: { labels: string[]; mentioned_details: string[]; proposed_value: number | null };
  state: { trust: number; readiness: number; irritation: number; position: number };
};

export type SessionResult = {
  session_id: string;
  status: string;
  outcome: string | null;
  incomplete: boolean;
  final_position: number | null;
  in_zone: boolean | null;
  position_shift: number | null;
  details_covered: string[];
  details_missed: string[];
  judge: { axes: Record<string, number>; key_moments: { quote: string; problem: string; better: string }[]; next_scenario_hint: string } | null;
  judge_source: "llm" | "rules" | null;
};

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
  messages: { role: "user" | "opponent"; text: string; labels: string[] }[];
};

export const store = {
  get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string | null) => { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* приватный режим */ } },
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const token = store.get("arena.adminToken");
  const r = await fetch(path, { headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) }, ...init });
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail;
    throw new Error(Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail ?? r.statusText);
  }
  return r.json();
}

export const api = {
  scenarios: () => call<Scenario[]>("/api/scenarios"),
  createScenario: (card: ScenarioCard) => call<Scenario>("/api/scenarios", { method: "POST", body: JSON.stringify(card) }),
  updateScenario: (id: string, card: ScenarioCard) => call<Scenario>(`/api/scenarios/${id}`, { method: "PUT", body: JSON.stringify(card) }),
  generate: (description: string) => call<ScenarioCard>("/api/scenarios/generate", { method: "POST", body: JSON.stringify({ description }) }),
  start: (id: string) => call<{ session_id: string; opening: string; max_turns: number }>(`/api/sessions?scenario_id=${id}`, { method: "POST" }),
  turn: (sid: string, message: string) => call<TurnOut>(`/api/sessions/${sid}/turn`, { method: "POST", body: JSON.stringify({ message }) }),
  finish: (sid: string) => call<{ ok: boolean }>(`/api/sessions/${sid}/finish`, { method: "POST" }),
  result: (sid: string) => call<SessionResult>(`/api/sessions/${sid}/result`),
  session: (sid: string) => call<SessionView>(`/api/sessions/${sid}`),
  rewind: (sid: string, turn: number) => call<SessionView>(`/api/sessions/${sid}/rewind`, { method: "POST", body: JSON.stringify({ turn }) }),
  history: () => call<{ id: string; scenario: string; status: string; outcome: string | null; turns: number }[]>("/api/sessions"),
};
