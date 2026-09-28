import type { ReactNode } from "react";

const Svg = ({ children, size = 18 }: { children: ReactNode; size?: number }) => (
  <svg className="i" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);

export const MicIcon = ({ size }: { size?: number }) => <Svg size={size}><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></Svg>;
export const StopIcon = () => <Svg><rect x="6" y="6" width="12" height="12" rx="2" /></Svg>;
export const TrashIcon = () => <Svg><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></Svg>;
export const SendIcon = () => <Svg><path d="M12 19V5M5 12l7-7 7 7" /></Svg>;

const PATHS: Record<string, ReactNode> = {
  send: <path d="M12 19V5M5 12l7-7 7 7" />,
  undo: <><path d="M9 14 4 9l5-5" /><path d="M4 9h10a6 6 0 0 1 0 12h-3" /></>,
  flag: <path d="M5 21V4M5 4h11l-2 4 2 4H5" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  back: <path d="M15 18l-6-6 6-6" />,
  down: <path d="M6 9l6 6 6-6" />,
  replay: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  copy: <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h8" /></>,
  edit: <><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="M13.5 6.5l4 4" /></>,
  logo: <><path d="M6 20V11a6 6 0 0 1 12 0v9" /><path d="M6 16h3.5M14.5 16H18" /></>,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  more: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  lock: <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>,
  box: <><path d="M3 7.5 12 3l9 4.5-9 4.5-9-4.5z" /><path d="M3 7.5v9L12 21l9-4.5v-9M12 12v9" /></>,
  users: <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14a6.5 6.5 0 0 1 3.5 6" /></>,
  clip: <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4V3h6v1M9 10h6M9 14h6M9 18h3" /></>,
  factory: <><path d="M3 21V10l6 4v-4l6 4V5h6v16z" /><path d="M7 17h2M12 17h2M17 17h1" /></>,
  case: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M9 7V5h6v2M3 12h18" /></>,
  fork: <><circle cx="6" cy="5" r="2" /><circle cx="6" cy="19" r="2" /><circle cx="18" cy="8" r="2" /><path d="M6 7v10M18 10c0 4-6 3-11.5 7.5" /></>,
  scales: <><path d="M12 3v18M7 21h10M5 7h14" /><path d="M5 7 2.5 13a3 3 0 0 0 5 0zM19 7l-2.5 6a3 3 0 0 0 5 0z" /></>,
  ask: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5v.01" /></>,
  chat: <path d="M4 5h16v11H9l-5 4z" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  turns: <path d="M4 7h13l-3-3M20 17H7l3 3" />,
  check: <path d="M5 12.5 10 17 19 7" />,
  book: <><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z" /><path d="M4 21V5M8 7h7" /></>,
};

export type IconName = keyof typeof PATHS;
export const Icon = ({ name, size = 18 }: { name: string; size?: number }) => <Svg size={size}>{PATHS[name] ?? PATHS.chat}</Svg>;
