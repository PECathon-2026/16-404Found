export const shortId = (id: string | null | undefined) => (id ? (id.length > 14 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id) : "—");
export const shortSha = (s: string | null | undefined) => (s ? s.slice(0, 10) : "—");
export function timeAgo(iso: string | undefined | null): string {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
export const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour12: false });
export const fmtNum = (n: number | null | undefined) => (n == null ? "no data" : n.toLocaleString());
