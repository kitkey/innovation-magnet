// Место под аватар собеседника: голос и аватар подключаются сюда отдельной задачей.
export default function OpponentAvatar({ role }: { role: string }) {
  return <div className="avatar-slot" data-slot="opponent-avatar">{role}</div>;
}
