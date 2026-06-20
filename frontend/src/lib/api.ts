export const API = "http://127.0.0.1:8000";

export interface ArchInfo {
  stats: Record<string, number>;
  agents: { name: string; desc: string }[];
  sources: { name: string; tech: string }[];
  guarantee: string;
  llm: string;
}

export async function getSuggestions(): Promise<string[]> {
  const r = await fetch(`${API}/api/suggestions`);
  return (await r.json()).suggestions ?? [];
}

export async function getArchitecture(): Promise<ArchInfo> {
  const r = await fetch(`${API}/api/architecture`);
  return await r.json();
}
