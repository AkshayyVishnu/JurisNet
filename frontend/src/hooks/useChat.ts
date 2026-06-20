import { useCallback, useRef, useState } from "react";
import { streamAsk } from "../lib/stream";

export interface Stage { name: string; message: string; done: boolean; }
export interface Source {
  tid: number; title: string; chunk_type: string;
  caution_flag: boolean; matched: string[];
}
export interface ChatState {
  status: "idle" | "streaming" | "done" | "error";
  query: string;
  intent?: string;
  entities: string[];
  stages: Stage[];
  sources: Source[];
  answer: string;
  confidence?: number;
  fabricated: number[];
  outOfContext: number[];
  elapsed?: number;
  error?: string;
}

const INITIAL: ChatState = {
  status: "idle", query: "", entities: [], stages: [],
  sources: [], answer: "", fabricated: [], outOfContext: [],
};

export function useChat() {
  const [state, setState] = useState<ChatState>(INITIAL);
  const [activeSource, setActiveSource] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL);
    setActiveSource(null);
  }, []);

  const ask = useCallback(async (query: string) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setActiveSource(null);
    setState({ ...INITIAL, status: "streaming", query });

    const onEvent = (event: string, data: any) => {
      setState((s) => {
        switch (event) {
          case "stage":
            return { ...s, stages: [...s.stages.map(st => ({ ...st, done: true })),
                                     { name: data.name, message: data.message, done: false }] };
          case "understood":
            return { ...s, intent: data.intent, entities: data.entities ?? [] };
          case "sources":
            return { ...s, sources: data.items ?? [] };
          case "token":
            return { ...s, answer: s.answer + (data.text ?? "") };
          case "verified":
            return { ...s, answer: data.answer ?? s.answer, confidence: data.confidence,
                     fabricated: data.fabricated ?? [], outOfContext: data.out_of_context ?? [] };
          case "done":
            return { ...s, status: "done", elapsed: data.elapsed_s,
                     stages: s.stages.map(st => ({ ...st, done: true })) };
          case "error":
            return { ...s, status: "error", error: data.message };
          default:
            return s;
        }
      });
    };

    try {
      await streamAsk(query, onEvent, ac.signal);
    } catch (e: any) {
      if (e?.name !== "AbortError")
        setState((s) => ({ ...s, status: "error", error: String(e?.message ?? e) }));
    }
  }, []);

  return { state, ask, reset, activeSource, setActiveSource };
}
