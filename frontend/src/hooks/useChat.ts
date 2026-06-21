import { useCallback, useRef, useState } from "react";
import { streamSSE } from "../lib/stream";

export type Mode = "fast" | "deep";

export interface Stage { name: string; message: string; done: boolean; }
export interface Source {
  tid: number; title: string; chunk_type: string; caution_flag: boolean; matched: string[];
}
export interface SubQ { id: number; text: string; query_type: string; pipeline: string; }
export interface Clarify {
  thread_id: string; type?: string; kind?: string; question: string; options: string[];
}
export interface SubAnswer {
  sub_question_id: number; conclusion: string; reasoning: string; citations: string[];
}
export interface Adjudication {
  ultimate_verdict?: string; sub_answers?: SubAnswer[];
  options?: string[]; synthesis_and_conflicts?: string;
}

export interface ChatState {
  status: "idle" | "streaming" | "clarifying" | "done" | "error";
  mode: Mode;
  query: string;
  intent?: string;
  entities: string[];
  stages: Stage[];
  sources: Source[];
  // fast path
  answer: string;
  confidence?: number;
  fabricated: number[];
  outOfContext: number[];
  // deep path
  subquestions: SubQ[];
  surfaced: string[];
  adjudication?: Adjudication;
  clarify?: Clarify;
  threadId?: string;
  elapsed?: number;
  error?: string;
}

const base = (mode: Mode, query = ""): ChatState => ({
  status: "idle", mode, query, entities: [], stages: [], sources: [],
  answer: "", fabricated: [], outOfContext: [], subquestions: [], surfaced: [],
});

export function useChat() {
  const [state, setState] = useState<ChatState>(base("fast"));
  const [activeSource, setActiveSource] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback((mode?: Mode) => {
    abortRef.current?.abort();
    setActiveSource(null);
    setState((s) => base(mode ?? s.mode));
  }, []);

  const onEvent = useCallback((event: string, data: any) => {
    setState((s) => {
      switch (event) {
        case "meta": return { ...s, threadId: data.thread_id };
        case "stage": return {
          ...s,
          stages: [...s.stages.map((st) => ({ ...st, done: true })),
                   { name: data.name, message: data.message, done: false }],
        };
        case "understood": return { ...s, intent: data.intent, entities: data.entities ?? [] };
        case "subquestions": return { ...s, subquestions: data.items ?? [] };
        case "sources": return { ...s, sources: data.items ?? [] };
        case "surfaced": return { ...s, surfaced: data.statutes ?? [] };
        case "token": return { ...s, answer: s.answer + (data.text ?? "") };
        case "verified": return {
          ...s, answer: data.answer ?? s.answer, confidence: data.confidence,
          fabricated: data.fabricated ?? [], outOfContext: data.out_of_context ?? [],
        };
        case "clarify": return { ...s, status: "clarifying", clarify: data };
        case "answer": return { ...s, adjudication: data };
        case "done": return {
          ...s, status: "done", elapsed: data.elapsed_s,
          stages: s.stages.map((st) => ({ ...st, done: true })),
        };
        case "error": return { ...s, status: "error", error: data.message };
        default: return s;
      }
    });
  }, []);

  const ask = useCallback(async (query: string, mode: Mode) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setActiveSource(null);
    setState({ ...base(mode, query), status: "streaming" });
    const path = mode === "fast" ? "/api/ask" : "/api/deep";
    try {
      await streamSSE(path, { query }, onEvent, ac.signal);
    } catch (e: any) {
      if (e?.name !== "AbortError")
        setState((s) => ({ ...s, status: "error", error: String(e?.message ?? e) }));
    }
  }, [onEvent]);

  const resume = useCallback(async (answer: string) => {
    const ac = new AbortController();
    abortRef.current = ac;
    let tid: string | undefined;
    setState((s) => { tid = s.threadId; return { ...s, status: "streaming", clarify: undefined }; });
    try {
      await streamSSE("/api/deep", { thread_id: tid, resume: answer }, onEvent, ac.signal);
    } catch (e: any) {
      if (e?.name !== "AbortError")
        setState((s) => ({ ...s, status: "error", error: String(e?.message ?? e) }));
    }
  }, [onEvent]);

  return { state, ask, resume, reset, activeSource, setActiveSource };
}
