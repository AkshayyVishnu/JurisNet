import { ShieldCheck, ShieldAlert } from "lucide-react";

export function ConfidenceBadge({ value, fabricated }: { value?: number; fabricated: number[] }) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  const clean = fabricated.length === 0 && pct >= 100;
  const color = clean ? "#15803d" : pct >= 70 ? "#b45309" : "#b91c1c";
  const bg = clean ? "#f0fdf4" : pct >= 70 ? "#fffbeb" : "#fef2f2";
  return (
    <div className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[13px] font-medium"
         style={{ background: bg, color }}>
      {clean ? <ShieldCheck size={15} /> : <ShieldAlert size={15} />}
      <span>{pct}% citations verified</span>
      {fabricated.length > 0 && <span className="opacity-80">· {fabricated.length} flagged</span>}
    </div>
  );
}
