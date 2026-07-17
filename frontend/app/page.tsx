"use client";

import {
  Brain,
  Check,
  CircleAlert,
  Compass,
  KeyRound,
  Loader2,
  Play,
  RefreshCcw,
  Send,
  ShieldCheck,
  Sparkles,
  SquareActivity,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  approveAction,
  sendChat,
  streamChat,
  type StreamEvent,
  type StreamMode,
} from "@/lib/api";

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
};

const SUGGESTIONS = [
  "I want to visit Japan from Bangladesh for 7 days with a budget of $2000",
  "Plan a Thailand trip for 5 days",
  "I prefer temple,food, culture",
];

const TRAVELER_ID_STORAGE_KEY = "travel-ai-user-id";

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: crypto.randomUUID(),
      role: "system",
      content:
        "Start a travel request, then refine it with preferences. The same thread id will keep the conversation state.",
    },
  ]);
  const [input, setInput] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [userId, setUserId] = useState("");
  const [streamMode, setStreamMode] = useState<StreamMode>("messages");
  const [useStreaming, setUseStreaming] = useState(false);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const visibleEvents = useMemo(
    () =>
      events
        .filter((event) => event.content.trim().length > 0)
        .slice(-18)
        .reverse(),
    [events],
  );

  useEffect(() => {
    const savedUserId = window.localStorage.getItem(TRAVELER_ID_STORAGE_KEY);
    const nextUserId = savedUserId || `traveler-${crypto.randomUUID()}`;

    window.localStorage.setItem(TRAVELER_ID_STORAGE_KEY, nextUserId);
    setUserId(nextUserId);
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();

    if (!message || isLoading) {
      return;
    }

    setInput("");
    setError(null);
    setIsLoading(true);
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: message,
      },
    ]);

    try {
      if (useStreaming) {
        await handleStreamingRequest(message);
      } else {
        await handleChatRequest(message);
      }
    } catch (caughtError) {
      const content =
        caughtError instanceof Error
          ? caughtError.message
          : "The request failed unexpectedly.";
      setError(content);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "system",
          content,
        },
      ]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  }

  async function handleChatRequest(message: string) {
    const response = await sendChat({
      message,
      thread_id: threadId,
      user_id: userId || null,
    });

    setThreadId(response.thread_id);
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.response,
      },
    ]);
  }

  async function handleStreamingRequest(message: string) {
    let assistantContent = "";
    let streamedThreadId = threadId;
    const assistantId = crypto.randomUUID();

    setMessages((current) => [
      ...current,
      {
        id: assistantId,
        role: "assistant",
        content: "",
      },
    ]);

    await streamChat(
      {
        message,
        thread_id: threadId,
        user_id: userId || null,
        stream_mode: streamMode,
      },
      (event) => {
        streamedThreadId = event.thread_id;
        setEvents((current) => [...current, event]);

        if (event.event_type === "on_chat_model_stream") {
          assistantContent += event.content;
          setMessages((current) =>
            current.map((item) =>
              item.id === assistantId
                ? {
                    ...item,
                    content: assistantContent,
                  }
                : item,
            ),
          );
        }
      },
    );

    setThreadId(streamedThreadId);
  }

  async function handleApproval(approved: boolean) {
    if (!threadId || isLoading) {
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await approveAction(threadId, approved);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "system",
          content: `Approval ${response.status} for thread ${response.thread_id}.`,
        },
      ]);
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Approval request failed.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  function resetThread() {
    setThreadId(null);
    setEvents([]);
    setError(null);
    setMessages([
      {
        id: crypto.randomUUID(),
        role: "system",
        content: "New travel thread started.",
      },
    ]);
  }

  function resetTravelerMemory() {
    const nextUserId = `traveler-${crypto.randomUUID()}`;

    window.localStorage.setItem(TRAVELER_ID_STORAGE_KEY, nextUserId);
    setUserId(nextUserId);
    setThreadId(null);
    setEvents([]);
    setError(null);
    setMessages([
      {
        id: crypto.randomUUID(),
        role: "system",
        content: "New traveler profile started. Long-term memory will use the new traveler id.",
      },
    ]);
  }

  function applySuggestion(suggestion: string) {
    setInput(suggestion);
    inputRef.current?.focus();
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandIcon">
            <Compass size={22} />
          </div>
          <div>
            <h1>Travel AI</h1>
            <p>LangGraph planning workspace</p>
          </div>
        </div>

        <section className="panel">
          <div className="panelHeader">
            <SquareActivity size={16} />
            <span>Session</span>
          </div>
          <div className="threadBox">
            <span>{threadId ?? "No thread yet"}</span>
          </div>
          <button className="secondaryButton" type="button" onClick={resetThread}>
            <RefreshCcw size={16} />
            Reset
          </button>
        </section>

        <section className="panel memoryPanel">
          <div className="panelHeader">
            <Brain size={16} />
            <span>Traveler Memory</span>
          </div>
          <div className="memoryState">
            <KeyRound size={15} />
            <span>{userId || "Creating traveler id..."}</span>
          </div>
          <button
            className="secondaryButton"
            type="button"
            onClick={resetTravelerMemory}
          >
            <RefreshCcw size={16} />
            New traveler
          </button>
        </section>

        <section className="panel">
          <div className="panelHeader">
            <Sparkles size={16} />
            <span>Mode</span>
          </div>
          <label className="toggleRow">
            <input
              checked={useStreaming}
              onChange={(event) => setUseStreaming(event.target.checked)}
              type="checkbox"
            />
            <span>Stream events</span>
          </label>
          <div className="segmented">
            {(["messages", "updates", "debug"] as StreamMode[]).map((mode) => (
              <button
                className={streamMode === mode ? "active" : ""}
                disabled={!useStreaming}
                key={mode}
                onClick={() => setStreamMode(mode)}
                type="button"
              >
                {mode}
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panelHeader">
            <ShieldCheck size={16} />
            <span>Approval</span>
          </div>
          <div className="approvalRow">
            <button
              className="iconButton accept"
              disabled={!threadId || isLoading}
              onClick={() => handleApproval(true)}
              title="Approve"
              type="button"
            >
              <Check size={18} />
            </button>
            <button
              className="iconButton reject"
              disabled={!threadId || isLoading}
              onClick={() => handleApproval(false)}
              title="Reject"
              type="button"
            >
              <X size={18} />
            </button>
          </div>
        </section>
      </aside>

      <section className="workspace">
        <div className="chatHeader">
          <div>
            <h2>Trip Conversation</h2>
            <p>Ask, refine, stream, and reuse traveler preferences across threads.</p>
          </div>
          <div className="statusPill">
            {isLoading ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
            {isLoading ? "Running" : "Ready"}
          </div>
        </div>

        <div className="contentGrid">
          <section className="chatSurface">
            <div className="messages">
              {messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <span>{message.role}</span>
                  <p>{message.content || "Streaming..."}</p>
                </article>
              ))}
              {error ? (
                <article className="message error">
                  <span>
                    <CircleAlert size={14} />
                    error
                  </span>
                  <p>{error}</p>
                </article>
              ) : null}
            </div>

            <div className="suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  disabled={isLoading}
                  key={suggestion}
                  onClick={() => applySuggestion(suggestion)}
                  type="button"
                >
                  {suggestion}
                </button>
              ))}
            </div>

            <form className="composer" onSubmit={handleSubmit}>
              <textarea
                disabled={isLoading}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Tell the agent where you want to go..."
                ref={inputRef}
                rows={3}
                value={input}
              />
              <button disabled={isLoading || input.trim().length === 0} type="submit">
                {isLoading ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
                Send
              </button>
            </form>
          </section>

          <aside className="eventRail">
            <div className="railHeader">
              <h3>Live Events</h3>
              <span>{events.length}</span>
            </div>
            <div className="eventList">
              {visibleEvents.length === 0 ? (
                <p className="emptyEvents">Enable streaming to inspect graph events.</p>
              ) : (
                visibleEvents.map((event, index) => (
                  <article className="eventItem" key={`${event.timestamp}-${index}`}>
                    <div>
                      <strong>{event.node}</strong>
                      <span>{event.event_type}</span>
                    </div>
                    <p>{event.content}</p>
                  </article>
                ))
              )}
            </div>
          </aside>
        </div>
      </section>
    </main>
  );
}
