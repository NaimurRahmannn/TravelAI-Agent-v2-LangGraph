"use client";

import {
  Brain,
  Check,
  CircleAlert,
  Compass,
  KeyRound,
  Loader2,
  MapPinned,
  Play,
  RefreshCcw,
  Send,
  ShieldCheck,
  SquareActivity,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  approveAction,
  sendChat,
  type DetailedRoutingPlan,
  type TravelSelections,
  type TripCostSummary,
  type TripPlan,
} from "@/lib/api";
import { AssistantMessage } from "@/components/AssistantMessage";
import { buildItineraryMapPoints } from "@/lib/itineraryMap";

type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  itinerary?: TripPlan | null;
  travelSelections?: TravelSelections | null;
  tripCostSummary?: TripCostSummary | null;
  detailedRoutingPlan?: DetailedRoutingPlan | null;
  missingFields?: string[];
};

const SUGGESTIONS = [
  "I want to visit Japan from Bangladesh",
  "Plan a Thailand trip for 5 days",
  "I prefer temple, mountain, river",
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
  const [mapRailTarget, setMapRailTarget] = useState<HTMLDivElement | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const dateUpdateInFlightRef = useRef(false);

  const editableItineraryMessageId = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].itinerary) {
        return messages[index].id;
      }
    }
    return null;
  }, [messages]);
  const latestItinerary = useMemo(
    () =>
      messages.find((message) => message.id === editableItineraryMessageId)
        ?.itinerary ?? null,
    [editableItineraryMessageId, messages],
  );
  const selectableItineraryMessageId = useMemo(() => {
    const latestMessage = messages[messages.length - 1];
    return latestMessage?.role === "assistant" && latestMessage.itinerary
      ? latestMessage.id
      : null;
  }, [messages]);
  const latestItineraryHasMapPoints = useMemo(
    () =>
      latestItinerary
        ? buildItineraryMapPoints(latestItinerary, "map-rail-preview").length > 0
        : false,
    [latestItinerary],
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
      await handleChatRequest(message);
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
        itinerary: response.itinerary,
        travelSelections: response.travel_selections,
        tripCostSummary: response.trip_cost_summary,
        detailedRoutingPlan: response.detailed_routing_plan,
        missingFields: response.missing_fields,
      },
    ]);
  }

  async function handleDateSelection(
    sourceMessageId: string,
    startDate: string,
    endDate: string,
  ) {
    if (isLoading) {
      return;
    }

    setError(null);
    setIsLoading(true);
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: `Travel dates: ${startDate} to ${endDate}`,
      },
    ]);

    try {
      const response = await sendChat({
        message: "I selected my exact travel dates.",
        thread_id: threadId,
        user_id: userId || null,
        start_date: startDate,
        end_date: endDate,
      });

      setThreadId(response.thread_id);
      setMessages((current) => [
        ...current.map((item) =>
          item.id === sourceMessageId
            ? {
                ...item,
                missingFields: item.missingFields?.filter(
                  (field) => field !== "dates",
                ),
              }
            : item,
        ),
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.response,
          itinerary: response.itinerary,
          travelSelections: response.travel_selections,
          tripCostSummary: response.trip_cost_summary,
          detailedRoutingPlan: response.detailed_routing_plan,
          missingFields: response.missing_fields,
        },
      ]);
    } catch (caughtError) {
      const content =
        caughtError instanceof Error
          ? caughtError.message
          : "The date selection failed unexpectedly.";
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

  async function handleDateUpdate(
    sourceMessageId: string,
    startDate: string,
    endDate: string,
  ) {
    if (dateUpdateInFlightRef.current || isLoading) {
      throw new Error("A date update is already in progress.");
    }
    if (!threadId) {
      throw new Error("The current travel thread is unavailable.");
    }

    dateUpdateInFlightRef.current = true;
    setError(null);
    setIsLoading(true);
    try {
      const response = await sendChat({
        message: "I changed my exact travel dates.",
        thread_id: threadId,
        user_id: userId || null,
        start_date: startDate,
        end_date: endDate,
      });
      if (!response.itinerary) {
        throw new Error(
          "The itinerary could not be regenerated. Please try again.",
        );
      }
      if (response.thread_id !== threadId) {
        throw new Error("The date update did not retain the current thread.");
      }

      setMessages((current) =>
        current.map((item) =>
          item.id === sourceMessageId
            ? {
                ...item,
                content: response.response,
                itinerary: response.itinerary,
                travelSelections: response.travel_selections,
                tripCostSummary: response.trip_cost_summary,
                detailedRoutingPlan: response.detailed_routing_plan,
                missingFields: response.missing_fields,
              }
            : item,
        ),
      );
    } catch (caughtError) {
      if (caughtError instanceof Error) {
        throw caughtError;
      }
      throw new Error("Unable to update the travel dates. Please try again.");
    } finally {
      dateUpdateInFlightRef.current = false;
      setIsLoading(false);
    }
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

  function handleTravelSelectionConfirmed(
    sourceMessageId: string,
    selections: TravelSelections,
    costSummary: TripCostSummary,
  ) {
    setMessages((current) =>
      current.map((item) =>
        item.id === sourceMessageId
          ? {
              ...item,
              travelSelections: selections,
              tripCostSummary: costSummary,
              detailedRoutingPlan: null,
            }
          : item,
      ),
    );
  }

  function handleDetailedRoutingGenerated(
    sourceMessageId: string,
    detailedRoutingPlan: DetailedRoutingPlan,
  ) {
    setMessages((current) =>
      current.map((item) =>
        item.id === sourceMessageId
          ? { ...item, detailedRoutingPlan }
          : item,
      ),
    );
  }

  function handleFlightsRefreshed(
    sourceMessageId: string,
    itinerary: TripPlan,
  ) {
    setMessages((current) =>
      current.map((item) =>
        item.id === sourceMessageId
          ? {
              ...item,
              itinerary,
              travelSelections: null,
              tripCostSummary: null,
              detailedRoutingPlan: null,
            }
          : item,
      ),
    );
  }

  function resetThread() {
    setThreadId(null);
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
          <button
            className="secondaryButton"
            disabled={isLoading}
            onClick={resetThread}
            type="button"
          >
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
            disabled={isLoading}
            type="button"
            onClick={resetTravelerMemory}
          >
            <RefreshCcw size={16} />
            New traveler
          </button>
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
            <p>Ask, refine, and reuse traveler preferences across threads.</p>
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
                <article
                  className={`message ${message.role} ${
                    message.itinerary ? "itineraryMessage" : ""
                  }`}
                  key={message.id}
                >
                  <span>{message.role}</span>
                  {message.role === "assistant" ? (
                    <AssistantMessage
                      content={message.content}
                      detailedRoutingPlan={message.detailedRoutingPlan}
                      itinerary={message.itinerary}
                      isLoading={isLoading}
                      mapPortalTarget={mapRailTarget}
                      missingFields={message.missingFields}
                      onTravelSelectionConfirmed={(selections, costSummary) =>
                        handleTravelSelectionConfirmed(
                          message.id,
                          selections,
                          costSummary,
                        )
                      }
                      onDetailedRoutingGenerated={(plan) =>
                        handleDetailedRoutingGenerated(message.id, plan)
                      }
                      onFlightsRefreshed={(itinerary) =>
                        handleFlightsRefreshed(message.id, itinerary)
                      }
                      onDateContinue={(startDate, endDate) =>
                        handleDateSelection(message.id, startDate, endDate)
                      }
                      onDateUpdate={
                        message.id === editableItineraryMessageId
                          ? (startDate, endDate) =>
                              handleDateUpdate(
                                message.id,
                                startDate,
                                endDate,
                              )
                          : undefined
                      }
                      showMap={message.id === editableItineraryMessageId}
                      threadId={
                        message.id === selectableItineraryMessageId && !isLoading
                          ? threadId
                          : null
                      }
                      travelSelections={message.travelSelections}
                      tripCostSummary={message.tripCostSummary}
                    />
                  ) : (
                    <p>{message.content}</p>
                  )}
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
          <aside aria-label="Trip map" className="mapRail">
            <div className="mapRailContent" ref={setMapRailTarget}>
              {!latestItineraryHasMapPoints ? (
                <div className="mapRailPlaceholder">
                  <span>
                    <MapPinned aria-hidden="true" size={24} />
                  </span>
                  <div>
                    <h3>Trip map</h3>
                    <p>
                      {latestItinerary
                        ? "No resolved itinerary places are available to map yet."
                        : "Your generated itinerary map will appear here."}
                    </p>
                  </div>
                </div>
              ) : null}
            </div>
          </aside>
        </div>
      </section>
    </main>
  );
}
