import { Zap, Microscope } from "lucide-react";
import type { Mode } from "../hooks/useChat";

export function ModeToggle({ mode, onChange, disabled }: {
  mode: Mode; onChange: (m: Mode) => void; disabled?: boolean;
}) {
  const opts: { key: Mode; label: string; icon: any; hint: string }[] = [
    { key: "fast", label: "Fast", icon: Zap, hint: "Retrieve → synthesize → verify citations" },
    { key: "deep", label: "Deep analysis", icon: Microscope, hint: "Checklist + fact audit (may ask you questions)" },
  ];
  return (
    <div className="inline-flex rounded-xl border border-[var(--line)] p-0.5 bg-neutral-50">
      {opts.map((o) => {
        const on = mode === o.key;
        const Icon = o.icon;
        return (
          <button
            key={o.key}
            disabled={disabled}
            title={o.hint}
            onClick={() => onChange(o.key)}
            className={"flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition disabled:opacity-50 " +
              (on ? "bg-white shadow-sm text-black font-medium" : "text-neutral-500 hover:text-black")}
          >
            <Icon size={14} className={on ? "text-[var(--accent)]" : ""} /> {o.label}
          </button>
        );
      })}
    </div>
  );
}
