import ReactMarkdown from "react-markdown";
import { motion } from "framer-motion";
import { ConfidenceBadge } from "./ConfidenceBadge";

/** Turn [tid 123] / [tid 123 ⚠UNVERIFIED] into markdown links the renderer can style. */
function preprocess(md: string): string {
  return md
    .replace(/\[tid\s*(-?\d+)\s*⚠UNVERIFIED\]/gi, (_m, n) => `[unv${n}](cite:${n}?u=1)`)
    .replace(/\[tid\s*(-?\d+)\]/gi, (_m, n) => `[tid${n}](cite:${n})`);
}

export function AnswerPane({ answer, confidence, fabricated, elapsed, onCite }: {
  answer: string; confidence?: number; fabricated: number[];
  elapsed?: number; onCite: (tid: number) => void;
}) {
  if (!answer) return null;
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-[var(--line)] bg-white p-5 sm:p-6">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] uppercase tracking-widest text-neutral-400">Answer</span>
        <div className="flex items-center gap-3">
          {elapsed != null && <span className="text-xs text-neutral-400">{elapsed}s</span>}
          <ConfidenceBadge value={confidence} fabricated={fabricated} />
        </div>
      </div>

      <div className="prose-legal text-[15px]">
        <ReactMarkdown
          components={{
            a: ({ href, children }) => {
              const m = /^cite:(-?\d+)(\?u=1)?$/.exec(String(href ?? ""));
              if (!m) return <a href={href}>{children}</a>;
              const tid = Number(m[1]);
              const unverified = !!m[2];
              return (
                <button
                  onClick={() => onCite(tid)}
                  title={unverified ? "Unverified citation" : `Source ${tid}`}
                  className={
                    "align-baseline mx-0.5 rounded px-1.5 py-0.5 text-[12px] font-medium transition " +
                    (unverified
                      ? "bg-red-50 text-red-700 hover:bg-red-100"
                      : "bg-[var(--accent-soft)] text-[var(--accent)] hover:brightness-95")
                  }
                >
                  {unverified ? `⚠ ${tid}` : tid}
                </button>
              );
            },
          }}
        >
          {preprocess(answer)}
        </ReactMarkdown>
      </div>
    </motion.div>
  );
}
