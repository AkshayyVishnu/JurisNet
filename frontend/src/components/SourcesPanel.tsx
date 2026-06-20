import { motion } from "framer-motion";
import { AlertTriangle, Scale, BookText, ScrollText } from "lucide-react";
import type { Source } from "../hooks/useChat";

const TYPE_META: Record<string, { label: string; icon: any; cls: string }> = {
  statute_provision: { label: "Statute", icon: BookText, cls: "bg-blue-50 text-blue-700" },
  rule_provision: { label: "Rule", icon: ScrollText, cls: "bg-violet-50 text-violet-700" },
  default: { label: "Judgment", icon: Scale, cls: "bg-emerald-50 text-emerald-700" },
};

function meta(t: string) { return TYPE_META[t] ?? TYPE_META.default; }

export function SourcesPanel({ sources, active, onHover }: {
  sources: Source[]; active: number | null; onHover: (tid: number | null) => void;
}) {
  if (!sources.length) return null;
  return (
    <div>
      <div className="text-[11px] uppercase tracking-widest text-neutral-400 mb-2">
        Sources · {sources.length}
      </div>
      <div className="space-y-2">
        {sources.map((s, i) => {
          const m = meta(s.chunk_type);
          const Icon = m.icon;
          const on = active === s.tid;
          return (
            <motion.div
              key={`${s.tid}-${i}`}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.02 }}
              onMouseEnter={() => onHover(s.tid)} onMouseLeave={() => onHover(null)}
              className={"rounded-lg border p-2.5 transition " +
                (on ? "border-[var(--accent)] bg-[var(--accent-soft)]" : "border-[var(--line)] bg-white")}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={"inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium " + m.cls}>
                  <Icon size={11} /> {m.label}
                </span>
                <span className="text-[11px] text-neutral-400 font-mono">#{s.tid}</span>
                {s.caution_flag && (
                  <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-amber-600">
                    <AlertTriangle size={11} /> caution
                  </span>
                )}
              </div>
              <div className="text-[13px] leading-snug text-neutral-700 line-clamp-2">{s.title || "—"}</div>
              {s.matched?.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {s.matched.map((mt) => (
                    <span key={mt} className="text-[10px] rounded bg-neutral-100 text-neutral-500 px-1.5 py-0.5">
                      {mt.replace("_vector", "").replace("citation_graph", "graph")}
                    </span>
                  ))}
                </div>
              )}
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
