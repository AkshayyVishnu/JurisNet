import { useEffect, useRef, useState } from "react";
import { Scale, Network, RotateCcw } from "lucide-react";
import { useChat } from "./hooks/useChat";
import { getSuggestions } from "./lib/api";
import { SuggestedChips } from "./components/SuggestedChips";
import { QueryBar } from "./components/QueryBar";
import { StageTracker } from "./components/StageTracker";
import { AnswerPane } from "./components/AnswerPane";
import { SourcesPanel } from "./components/SourcesPanel";
import { ArchitecturePanel } from "./components/ArchitecturePanel";

export default function App() {
  const { state, ask, reset, activeSource, setActiveSource } = useChat();
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [archOpen, setArchOpen] = useState(false);
  const answerRef = useRef<HTMLDivElement>(null);

  useEffect(() => { getSuggestions().then(setSuggestions).catch(() => {}); }, []);
  useEffect(() => {
    if (state.answer) answerRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [state.status]);

  const busy = state.status === "streaming";
  const started = state.status !== "idle";

  return (
    <div className="min-h-full">
      {/* Header */}
      <header className="sticky top-0 z-30 bg-white/80 backdrop-blur border-b border-[var(--line)]">
        <div className="max-w-6xl mx-auto px-5 h-14 flex items-center justify-between">
          <button onClick={reset} className="flex items-center gap-2">
            <span className="grid place-items-center h-7 w-7 rounded-lg bg-black text-white">
              <Scale size={16} />
            </span>
            <span className="font-semibold tracking-tight">JurisNet</span>
            <span className="hidden sm:inline text-xs text-neutral-400">· grounded Indian civil-law research</span>
          </button>
          <div className="flex items-center gap-1">
            {started && (
              <button onClick={reset}
                className="flex items-center gap-1.5 text-sm text-neutral-500 hover:text-black px-3 py-1.5 rounded-lg hover:bg-neutral-100">
                <RotateCcw size={15} /> New
              </button>
            )}
            <button onClick={() => setArchOpen(true)}
              className="flex items-center gap-1.5 text-sm text-neutral-600 hover:text-black px-3 py-1.5 rounded-lg hover:bg-neutral-100">
              <Network size={15} /> Architecture
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-5 py-8 grid lg:grid-cols-[1fr_320px] gap-8">
        {/* Conversation column */}
        <div className="space-y-5">
          {!started && (
            <div className="pt-6">
              <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">
                Ask anything about Indian civil procedure.
              </h1>
              <p className="mt-3 text-neutral-500 max-w-xl">
                Every answer is retrieved from 1,071 judgments, statutes & CPC rules —
                then <span className="text-[var(--accent)]">every citation is verified</span>.
              </p>
              <div className="mt-6"><SuggestedChips items={suggestions} onPick={ask} /></div>
            </div>
          )}

          {started && (
            <div className="rounded-lg text-sm text-neutral-500">
              <span className="text-neutral-400">You asked</span>
              <p className="text-[15px] text-neutral-900 mt-0.5">{state.query}</p>
            </div>
          )}

          <StageTracker
            stages={state.stages} intent={state.intent}
            sourceCount={state.sources.length || undefined} confidence={state.confidence}
          />

          {state.error && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {state.error}
            </div>
          )}

          <div ref={answerRef}>
            <AnswerPane
              answer={state.answer} confidence={state.confidence}
              fabricated={state.fabricated} elapsed={state.elapsed} onCite={setActiveSource}
            />
          </div>

          <QueryBar onSubmit={ask} busy={busy} />
        </div>

        {/* Sources rail */}
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
