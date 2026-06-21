import { useEffect, useRef, useState } from "react";
import { Scale, Network, RotateCcw } from "lucide-react";
import { useChat, type Mode } from "./hooks/useChat";
import { getSuggestions } from "./lib/api";
import { SuggestedChips } from "./components/SuggestedChips";
import { QueryBar } from "./components/QueryBar";
import { ModeToggle } from "./components/ModeToggle";
import { StageTracker } from "./components/StageTracker";
import { AnswerPane } from "./components/AnswerPane";
import { AdjudicationView } from "./components/AdjudicationView";
import { ClarifyPrompt } from "./components/ClarifyPrompt";
import { SourcesPanel } from "./components/SourcesPanel";
import { ArchitecturePanel } from "./components/ArchitecturePanel";

export default function App() {
  const { state, ask, resume, reset, activeSource, setActiveSource } = useChat();
  const [mode, setMode] = useState<Mode>("fast");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [archOpen, setArchOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => { getSuggestions().then(setSuggestions).catch(() => {}); }, []);
  useEffect(() => {
    if (state.answer || state.adjudication || state.clarify)
      scrollRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [state.status]);

  const busy = state.status === "streaming" || state.status === "clarifying";
  const started = state.status !== "idle";
  const submit = (q: string) => ask(q, mode);
  const changeMode = (m: Mode) => { setMode(m); reset(m); };

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-30 bg-white/80 backdrop-blur border-b border-[var(--line)]">
        <div className="max-w-6xl mx-auto px-5 h-14 flex items-center justify-between">
          <button onClick={() => reset(mode)} className="flex items-center gap-2">
            <span className="grid place-items-center h-7 w-7 rounded-lg bg-black text-white"><Scale size={16} /></span>
            <span className="font-semibold tracking-tight">JurisNet</span>
            <span className="hidden sm:inline text-xs text-neutral-400">· grounded Indian civil-law research</span>
          </button>
          <div className="flex items-center gap-2">
            <ModeToggle mode={mode} onChange={changeMode} disabled={busy} />
            {started && (
              <button onClick={() => reset(mode)}
                className="flex items-center gap-1.5 text-sm text-neutral-500 hover:text-black px-2 py-1.5 rounded-lg hover:bg-neutral-100">
                <RotateCcw size={15} /> New
              </button>
            )}
            <button onClick={() => setArchOpen(true)}
              className="flex items-center gap-1.5 text-sm text-neutral-600 hover:text-black px-2 py-1.5 rounded-lg hover:bg-neutral-100">
              <Network size={15} /> Architecture
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-5 py-8 grid lg:grid-cols-[1fr_320px] gap-8">
        <div className="space-y-5">
          {!started && (
            <div className="pt-6">
              <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">
                Ask anything about Indian civil procedure.
              </h1>
              <p className="mt-3 text-neutral-500 max-w-xl">
                Retrieved from 1,071 judgments, statutes & CPC rules.{" "}
                <span className="text-[var(--accent)]">Fast</span> streams a cited answer;{" "}
                <span className="text-[var(--accent)]">Deep analysis</span> audits the statutory checklist
                against your facts.
              </p>
              <div className="mt-6"><SuggestedChips items={suggestions} onPick={submit} /></div>
            </div>
          )}

          {started && (
            <div className="text-sm">
              <span className="text-neutral-400">You asked · {state.mode === "deep" ? "Deep analysis" : "Fast"}</span>
              <p className="text-[15px] text-neutral-900 mt-0.5">{state.query}</p>
            </div>
          )}

          {/* deep: sub-question split */}
          {state.mode === "deep" && state.subquestions.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {state.subquestions.map((sq) => (
                <span key={sq.id} className="text-[12px] rounded-lg border border-[var(--line)] px-2.5 py-1 text-neutral-600">
                  <span className="text-neutral-400">{sq.query_type === "test_application" ? "audit" : "info"} ·</span> {sq.text.length > 60 ? sq.text.slice(0, 60) + "…" : sq.text}
                </span>
              ))}
            </div>
          )}

          <StageTracker
            stages={state.stages} intent={state.intent}
            sourceCount={state.sources.length || undefined} confidence={state.confidence}
          />

          {state.error && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{state.error}</div>
          )}

          <div ref={scrollRef} className="space-y-5">
            {/* deep clarification */}
            {state.status === "clarifying" && state.clarify && (
              <ClarifyPrompt clarify={state.clarify} onAnswer={resume} />
            )}

            {/* results */}
            {state.mode === "fast" ? (
              <AnswerPane answer={state.answer} confidence={state.confidence}
                fabricated={state.fabricated} elapsed={state.elapsed} onCite={setActiveSource} />
            ) : (
              state.adjudication && <AdjudicationView adj={state.adjudication} elapsed={state.elapsed} />
            )}
          </div>

          <QueryBar onSubmit={submit} busy={busy} />
        </div>

        <aside className="lg:sticky lg:top-20 h-fit">
          <SourcesPanel sources={state.sources} active={activeSource} onHover={setActiveSource} />
          {!started && (
            <p className="text-xs text-neutral-400 leading-relaxed">
              Sources appear here as they're retrieved — judgments, statutes and CPC rules,
              tagged by which search found them.
            </p>
          )}
        </aside>
      </main>

      <ArchitecturePanel open={archOpen} onClose={() => setArchOpen(false)} />
    </div>
  );
}
