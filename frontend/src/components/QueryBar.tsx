import { useState } from "react";
import { Send, Loader2 } from "lucide-react";

export function QueryBar({ onSubmit, busy }: { onSubmit: (q: string) => void; busy: boolean }) {
  const [v, setV] = useState("");
  const submit = () => {
    const q = v.trim();
    if (q && !busy) { onSubmit(q); }
  };
  return (
    <div className="flex items-center gap-2 rounded-2xl border border-[var(--line)] bg-white
                    px-3 py-2 shadow-sm focus-within:border-[var(--accent)] transition">
      <input
        value={v}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        placeholder="Ask a civil-law question…"
        disabled={busy}
        className="flex-1 bg-transparent outline-none px-2 py-1.5 text-[15px] placeholder:text-neutral-400"
      />
      <button
        onClick={submit}
        disabled={busy || !v.trim()}
        className="grid place-items-center h-9 w-9 rounded-xl text-white
                   bg-[var(--accent)] disabled:opacity-40 hover:opacity-90 transition"
        aria-label="Ask"
      >
        {busy ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
      </button>
    </div>
  );
}
