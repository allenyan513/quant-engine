import { BacktestParams, BacktestResult, Session, SessionListItem } from "@/types";

const API_BASE = "/api";

export async function createSession(title: string = ""): Promise<{ id: string; created_at: string }> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return res.json();
}

export async function listSessions(): Promise<SessionListItem[]> {
  const res = await fetch(`${API_BASE}/sessions`);
  return res.json();
}

export async function getSession(id: string): Promise<Session> {
  const res = await fetch(`${API_BASE}/sessions/${id}`);
  return res.json();
}

export async function deleteSession(id: string): Promise<void> {
  await fetch(`${API_BASE}/sessions/${id}`, { method: "DELETE" });
}

export async function updateCode(sessionId: string, code: string): Promise<void> {
  await fetch(`${API_BASE}/sessions/${sessionId}/code`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}

export async function updateParams(sessionId: string, params: BacktestParams): Promise<void> {
  await fetch(`${API_BASE}/sessions/${sessionId}/params`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function getResults(sessionId: string): Promise<BacktestResult[]> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/results`);
  return res.json();
}

// ---------------------------------------------------------------------------
// SSE helpers
// ---------------------------------------------------------------------------

export type ChatSSEEvent =
  | { type: "text"; content: string }
  | { type: "code"; content: string }
  | { type: "error"; content: string }
  | { type: "done" };

export type BacktestSSEEvent =
  | { type: "status"; content: string; progress: number }
  | { type: "progress"; content: string; progress: number }
  | { type: "fix"; content: string; progress: number }
  | { type: "code"; content: string }
  | { type: "error_retry"; content: string }
  | { type: "error"; content: string }
  | { type: "result"; content: BacktestResult; result_id: number }
  | { type: "done" };

export async function streamChat(
  sessionId: string,
  message: string,
  onEvent: (event: ChatSSEEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });

  if (!res.ok) {
    const err = await res.text();
    onEvent({ type: "error", content: err });
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const event = JSON.parse(line.slice(6));
          onEvent(event);
        } catch {
          // ignore parse errors
        }
      }
    }
  }
}

export async function streamBacktest(
  sessionId: string,
  onEvent: (event: BacktestSSEEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/backtest`, {
    method: "POST",
  });

  if (!res.ok) {
    const err = await res.text();
    onEvent({ type: "error", content: err });
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const event = JSON.parse(line.slice(6));
          onEvent(event);
        } catch {
          // ignore
        }
      }
    }
  }
}
