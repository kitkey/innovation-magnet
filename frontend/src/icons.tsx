import type { ReactNode } from "react";

const Svg = ({ children, size = 18 }: { children: ReactNode; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);

export const MicIcon = ({ size }: { size?: number }) => <Svg size={size}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></Svg>;
export const StopIcon = () => <Svg><rect x="6" y="6" width="12" height="12" rx="2" /></Svg>;
export const TrashIcon = () => <Svg><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" /></Svg>;
export const SendIcon = () => <Svg><path d="M4 12l16-8-6 16-2-7z" /></Svg>;
