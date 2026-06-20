import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";

export function SuggestedChips({ items, onPick }: { items: string[]; onPick: (q: string) => void }) {
  return (
    <div className="grid sm:grid-cols-2 gap-3">
      {items.map((q, i) => (
        <motion.button
          key={q}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05 }}
          whileHover={{ y: -2 }}
          onClick={() => onPick(q)}
          className="group text-left rounded-xl border border-[var(--line)] px-4 py-3
                     hover:border-[var(--accent)] hover:shadow-sm transition
                     flex items-start justify-between gap-3"
        >
          <span className="text-[15px] text-neutral-700 group-hover:text-black">{q}</span>
          <ArrowUpRight size={16} className="mt-0.5 shrink-0 text-neutral-300 group-hover:text-[var(--accent)]" />
        </motion.button>
      ))}
    </div>
  );
}
