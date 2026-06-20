import { motion, AnimatePresence } from "framer-motion";
import { Check, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import type { Stage } from "../hooks/useChat";

export function StageTracker({ stages, intent, sourceCount, confidence }: {
  stages: Stage[]; intent?: string; sourceCount?: number; confidence?: number;
}) {
  if (!stages.length) return null;
  return (
    <div className="rounded-xl border border-[var(--line)] bg-neutral-50/60 p-4 space-y-2.5">
      <AnimatePresence initial={false}>
        {stages.map((s) => (
          <motion.div
            key={s.name}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center gap-3 text-[14px]"
          >
            <span className="grid place-items-center h-5 w-5 rounded-full shrink-0
                             border border-[var(--line)] bg-white">
              {s.done
                ? <Check size={13} className="text-[var(--accent)]" />
                : <Loader2 size={13} className="animate-spin text-neutral-400" />}
            </span>
            <span className={s.done ? "text-neutral-500" : "text-neutral-900 font-medium"}>
              {s.message}
            </span>
            {/* inline sub-details */}
            {s.name === "understanding" && s.done && intent && (
              <Tag>{intent}</Tag>
            )}
            {s.name === "retrieving" && s.done && sourceCount != null && (
              <Tag>{sourceCount} sources</Tag>
            )}
            {s.name === "verifying" && s.done && confidence != null && (
              <Tag>{Math.round(confidence * 100)}% grounded</Tag>
            )}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="ml-auto text-[11px] uppercase tracking-wide rounded-full
                     bg-[var(--accent-soft)] text-[var(--accent)] px-2 py-0.5">
      {children}
    </span>
  );
}
