import { motion } from "framer-motion";
import { Gavel, FileText, GitMerge } from "lucide-react";
import type { Adjudication } from "../hooks/useChat";

export function AdjudicationView({ adj, elapsed }: { adj: Adjudication; elapsed?: number }) {
  if (!adj || (!adj.ultimate_verdict && !(adj.sub_answers?.length))) return null;
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-[var(--line)] bg-white p-5 sm:p-6 space-y-5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-widest text-neutral-400">Adjudication</span>
        {elapsed != null && <span className="text-xs text-neutral-400">{elapsed}s</span>}
      </div>

      {adj.ultimate_verdict && (
        <div className="flex gap-3">
          <Gavel size={18} className="mt-0.5 shrink-0 text-[var(--accent)]" />
          <p className="text-[15px] leading-relaxed text-neutral-900 font-medium">{adj.ultimate_verdict}</p>
        </div>
      )}

      {adj.sub_answers?.map((sa) => (
        <div key={sa.sub_question_id} className="rounded-xl border border-[var(--line)] p-4">
          <div className="text-[14px] font-semibold text-black mb-1">{sa.conclusion}</div>
          <p className="text-[13px] text-neutral-600 leading-relaxed">{sa.reasoning}</p>
          {sa.citations?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {sa.citations.map((c, i) => (
                <span key={i} className="inline-flex items-center gap-1 rounded bg-[var(--accent-soft)]
                                         text-[var(--accent)] px-2 py-0.5 text-[11px]">
                  <FileText size={10} /> {c}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}

      {adj.synthesis_and_conflicts && (
        <div className="flex gap-3 border-t border-[var(--line)] pt-4">
          <GitMerge size={16} className="mt-0.5 shrink-0 text-neutral-400" />
          <p className="text-[13px] text-neutral-600 leading-relaxed">{adj.synthesis_and_conflicts}</p>
        </div>
      )}

      <p className="text-[11px] text-neutral-400 italic">
        Conclusions are audited against your stated facts — unstated facts are treated as unknown, not assumed.
      </p>
    </motion.div>
  );
}
