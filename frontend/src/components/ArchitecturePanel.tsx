import { useEffect, useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Workflow, Database, Network, ShieldCheck, Cpu } from "lucide-react";
import { getArchitecture, type ArchInfo } from "../lib/api";

const STAT_LABELS: [string, string][] = [
  ["documents", "Documents"],
  ["judgments", "Judgments"],
  ["statutes", "Statutes"],
  ["rules", "CPC Rules"],
  ["vector_chunks", "Vector chunks"],
  ["graph_edges", "Graph edges"],
];

export function ArchitecturePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [info, setInfo] = useState<ArchInfo | null>(null);
  useEffect(() => { if (open && !info) getArchitecture().then(setInfo).catch(() => {}); }, [open, info]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 bg-black/30 z-40"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.aside
            className="fixed right-0 top-0 h-full w-full max-w-md z-50 bg-white border-l border-[var(--line)]
                       overflow-y-auto p-6"
            initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 260 }}
          >
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold">How JurisNet works</h2>
              <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-neutral-100"><X size={18} /></button>
            </div>

            {/* live stats */}
            <Section icon={Database} title="Corpus & stores">
              <div className="grid grid-cols-3 gap-2">
                {STAT_LABELS.map(([k, label]) => (
                  <div key={k} className="rounded-lg border border-[var(--line)] p-2 text-center">
                    <div className="text-base font-semibold text-black">
                      {info?.stats?.[k]?.toLocaleString() ?? "—"}
                    </div>
                    <div className="text-[10px] uppercase tracking-wide text-neutral-400">{label}</div>
                  </div>
                ))}
              </div>
            </Section>

            <Section icon={Workflow} title="4-agent pipeline">
              <ol className="space-y-2">
                {info?.agents.map((a, i) => (
                  <li key={a.name} className="flex gap-3">
                    <span className="grid place-items-center h-6 w-6 shrink-0 rounded-full
                                     bg-[var(--accent-soft)] text-[var(--accent)] text-xs font-semibold">{i + 1}</span>
                    <div>
                      <div className="text-[13px] font-medium">{a.name}</div>
                      <div className="text-[12px] text-neutral-500">{a.desc}</div>
                    </div>
                  </li>
                ))}
              </ol>
            </Section>

            <Section icon={Network} title="Hybrid retrieval (RRF)">
              <div className="space-y-1.5">
                {info?.sources.map((s) => (
                  <div key={s.name} className="flex items-center justify-between text-[12px]">
                    <span className="font-medium text-neutral-700">{s.name}</span>
                    <span className="text-neutral-400">{s.tech}</span>
                  </div>
                ))}
              </div>
            </Section>

            <Section icon={ShieldCheck} title="Grounding guarantee">
              <p className="text-[12px] text-neutral-600">{info?.guarantee}</p>
            </Section>

            <Section icon={Cpu} title="LLM">
              <p className="text-[12px] text-neutral-600">{info?.llm}</p>
            </Section>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function Section({ icon: Icon, title, children }: { icon: any; title: string; children: ReactNode }) {
  return (
    <div className="mb-5">
      <div className="flex items-center gap-2 mb-2 text-neutral-500">
        <Icon size={15} /><span className="text-[12px] uppercase tracking-wide">{title}</span>
      </div>
      {children}
    </div>
  );
}
