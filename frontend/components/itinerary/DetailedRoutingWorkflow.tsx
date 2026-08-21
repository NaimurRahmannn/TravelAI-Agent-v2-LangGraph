import { Loader2, Route } from "lucide-react";
import type { DetailedRoutingPlan } from "@/lib/api";
import { DetailedRoutingTimeline } from "./DetailedRoutingTimeline";

type Props = {
  dismissed: boolean;
  error: string | null;
  loading: boolean;
  onCreate: () => void;
  onDismiss: () => void;
  plan?: DetailedRoutingPlan | null;
};

export function DetailedRoutingWorkflow({
  dismissed,
  error,
  loading,
  onCreate,
  onDismiss,
  plan,
}: Props) {
  if (plan) {
    return <DetailedRoutingTimeline plan={plan} />;
  }
  if (dismissed) {
    return null;
  }
  return (
    <section
      aria-labelledby="detailed-routing-prompt"
      className="detailedRoutingPrompt"
    >
      <div className="detailedRoutingPromptIcon">
        <Route aria-hidden="true" size={22} />
      </div>
      <div>
        <p className="selectionEyebrow">Next step</p>
        <h3 id="detailed-routing-prompt">
          Would you like me to create a detailed routing and timetable plan for
          your trip?
        </h3>
        <p>
          This reuses your selected flight, hotels, and itinerary. It does not
          search for travel again.
        </p>
        {error ? <p className="travelSelectionError" role="alert">{error}</p> : null}
        <div className="travelSelectionActions">
          <button disabled={loading} onClick={onCreate} type="button">
            {loading ? <Loader2 aria-hidden="true" className="spin" size={16} /> : null}
            {loading ? "Building your detailed routing plan..." : "Create routing plan"}
          </button>
          <button disabled={loading} onClick={onDismiss} type="button">
            Not now
          </button>
        </div>
      </div>
    </section>
  );
}
