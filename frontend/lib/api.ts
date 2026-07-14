export type StreamMode = "updates" | "messages" | "debug";

export type ChatRequest = {
  message: string;
  thread_id?: string | null;
  stream_mode?: StreamMode;
};

export type ChatResponse = {
  response: string;
  thread_id: string;
};

export type ApprovalResponse = {
  status: string;
  thread_id: string;
};

export type StreamEvent = {
  event_type: string;
  node: string;
  content: string;
  thread_id: string;
  timestamp: string;
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function sendChat(request: ChatRequest): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json();
}

export async function approveAction(
  threadId: string,
  approved: boolean,
): Promise<ApprovalResponse> {
  const response = await fetch(`${API_BASE_URL}/chat/approve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      thread_id: threadId,
      approved,
    }),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  return response.json();
}

export async function streamChat(
  request: ChatRequest,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok || response.body === null) {
    throw new Error(await getErrorMessage(response));
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const rawEvent of events) {
      const parsedEvent = parseServerSentEvent(rawEvent);
      if (parsedEvent !== null) {
        onEvent(parsedEvent);
      }
    }
  }
}

function parseServerSentEvent(rawEvent: string): StreamEvent | null {
  const dataLine = rawEvent
    .split("\n")
    .find((line) => line.startsWith("data: "));

  if (!dataLine) {
    return null;
  }

  try {
    return JSON.parse(dataLine.slice(6)) as StreamEvent;
  } catch {
    return null;
  }
}

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    return payload.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}
