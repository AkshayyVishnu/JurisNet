import { API } from "./api";

export type SSEHandler = (event: string, data: any) => void;

/** POST a JSON body and parse the SSE stream (fetch + ReadableStream; EventSource is GET-only). */
export async function streamSSE(path: string, body: any, onEvent: SSEHandler, signal?: AbortSignal) {
  const resp = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) throw new Error(`backend ${resp.status}`);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const frames = buf.split("\n\n");
    buf = frames.pop() ?? "";
    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data = line.slice(6);
      }
      if (data) {
        try { onEvent(event, JSON.parse(data)); } catch { /* ignore partial */ }
      }
    }
  }
}
