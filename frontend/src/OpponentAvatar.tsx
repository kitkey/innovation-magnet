import { Component, lazy, ReactNode, Suspense, useState } from "react";
import { Mood, ScenarioCard } from "./api";
import type { Say } from "./avatar/Avatar3D";
import { webglAvailable } from "./avatar/speech";

export type OpponentMode = "text" | "avatar";
export const DEFAULT_AVATAR = "/avatars/mpfb.glb";
const Avatar3D = lazy(() => import("./avatar/Avatar3D"));

// Ошибка загрузки чанка с three.js или падение внутри 3D не должны ронять диалог
class Guard extends Component<{ onError: (msg: string) => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e: Error) { this.props.onError(`3D не загрузился: ${e.message}`); }
  render() { return this.state.failed ? null : this.props.children; }
}

type Props = { role: string; mode: OpponentMode; avatarUrl: string | null; gender: ScenarioCard["voice"]; mood: Mood; say: Say | null; ttsReady: boolean; onSpeaking?: (on: boolean) => void };

export default function OpponentAvatar({ role, mode, avatarUrl, gender, mood, say, ttsReady, onSpeaking }: Props) {
  const [failed, setFailed] = useState("");
  if (mode === "text") return <div className="avatar-slot" data-slot="opponent-avatar">{role}</div>;
  const reason = failed || (webglAvailable() ? "" : "3D недоступен в этом браузере (нет WebGL)");
  if (reason) return <div className="avatar-slot" data-slot="opponent-avatar">{role}<span className="small">{reason}. Диалог идёт текстом.</span></div>;
  return (
    <Guard onError={setFailed}>
      <Suspense fallback={<div className="avatar-slot">Загружаем 3D…</div>}>
        <Avatar3D url={avatarUrl || DEFAULT_AVATAR} gender={gender} mood={mood} say={say} ttsReady={ttsReady} onFail={setFailed} onSpeaking={onSpeaking} />
      </Suspense>
    </Guard>
  );
}
