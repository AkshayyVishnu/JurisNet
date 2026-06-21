import { useState } from "react";
import { motion } from "framer-motion";
import { HelpCircle, CornerDownLeft } from "lucide-react";
import type { Clarify } from "../hooks/useChat";

export function ClarifyPrompt({ clarify, onAnswer }: {
  clarify: Clarify; onAnswer: (answer: string) => void;
}) {
  const [v, setV] = useState("");
  const submit = (a: string) => { if (a.trim()) onAnswer(a.trim()); };
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border-2 border-[var(--accent)] bg-[var(--accent-soft)] p-5">
      <div className="flex items-center gap-2 mb-2 text-[var(--accent)]">
        <HelpCircle size={16} />
        <span className="text-[11px] uppercase tracking-widest font-medium">
          The assistant needs a detail
        </span>
      </div>
      <p className="text-[15px] text-neutral-900 mb-3">{clarify.question}</p>

      {clarify.options?.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {clarify.options.map((o) => (
            <button key={o} onClick={() => submit(o)}
              className="rounded-lg border border-[var(--accent)] bg-white px-3 py-1.5 text-sm
                         text-[var(--accent)] hover:bg-[var(--accent)] hover:text-white transition">
              {o}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-white px-3 py-2">
        <input
          autoFocus value={v} onChange={(e) => setV(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(v); }}
          placeholder="Type your answer (or 'I don't know' to skip)…"
          className="flex-1 bg-transparent outline-none text-[14px] placeholder:text-neutral-400"
        />
        <button onClick={() => submit(v)} disabled={!v.trim()}
          className="flex items-center gap-1 text-sm text-[var(--accent)] disabled:opacity-40">
          Send <CornerDownLeft size={14} />
        </button>
      </div>
    </motion.div>
  );
}
