"use client";

import { DayPicker, type DateRange } from "@daypicker/react";
import { ArrowRight, CalendarDays, Loader2 } from "lucide-react";
import { FormEvent, useRef, useState } from "react";

const MAX_TRIP_DURATION_DAYS = 365;

type TravelDatePickerProps = {
  disabled?: boolean;
  initialEndDate?: string | null;
  initialStartDate?: string | null;
  onCancel?: () => void;
  onContinue: (startDate: string, endDate: string) => Promise<void> | void;
  submitLabel?: string;
  title?: string;
};

export function TravelDatePicker({
  disabled = false,
  initialEndDate,
  initialStartDate,
  onCancel,
  onContinue,
  submitLabel = "Continue",
  title = "When are you traveling?",
}: TravelDatePickerProps) {
  const today = startOfLocalDay(new Date());
  const [selected, setSelected] = useState<DateRange | undefined>(() =>
    createInitialRange(initialStartDate, initialEndDate),
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const submittingRef = useRef(false);
  const isComplete = selected?.from !== undefined && selected.to !== undefined;
  const isBusy = disabled || isSubmitting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected?.from || !selected.to || isBusy || submittingRef.current) {
      return;
    }

    submittingRef.current = true;
    setIsSubmitting(true);
    setSubmissionError(null);
    try {
      await onContinue(toIsoDate(selected.from), toIsoDate(selected.to));
    } catch (error) {
      setSubmissionError(getSubmissionError(error));
    } finally {
      submittingRef.current = false;
      setIsSubmitting(false);
    }
  }

  function handleSelect(range: DateRange | undefined) {
    setSelected(range);
    setSubmissionError(null);
  }

  return (
    <form className="travelDatePicker" onSubmit={handleSubmit}>
      <div className="datePickerHeading">
        <span className="datePickerIcon" aria-hidden="true">
          <CalendarDays size={19} />
        </span>
        <div>
          <h3>{title}</h3>
          <p>Select your arrival and departure dates.</p>
        </div>
      </div>

      <DayPicker
        className="travelCalendar"
        defaultMonth={selected?.from ?? today}
        disabled={{ before: today }}
        excludeDisabled
        max={MAX_TRIP_DURATION_DAYS - 1}
        mode="range"
        navLayout="after"
        onSelect={handleSelect}
        resetOnSelect
        selected={selected}
        showOutsideDays
      />

      <div className="selectedDateRange" aria-live="polite">
        <span>
          <small>Start date</small>
          <strong>
            {selected?.from ? formatSelectedDate(selected.from) : "Select"}
          </strong>
        </span>
        <ArrowRight aria-hidden="true" size={17} />
        <span>
          <small>End date</small>
          <strong>
            {selected?.to ? formatSelectedDate(selected.to) : "Select"}
          </strong>
        </span>
      </div>

      {submissionError ? (
        <p className="datePickerError" role="alert">
          {submissionError}
        </p>
      ) : null}

      <div className="datePickerActions">
        {onCancel ? (
          <button
            className="datePickerCancel"
            disabled={isBusy}
            onClick={onCancel}
            type="button"
          >
            Cancel
          </button>
        ) : null}
        <button
          className="datePickerContinue"
          disabled={!isComplete || isBusy}
          type="submit"
        >
          {isBusy ? <Loader2 className="spin" size={17} /> : null}
          {submitLabel}
        </button>
      </div>
    </form>
  );
}

function createInitialRange(
  startDate?: string | null,
  endDate?: string | null,
): DateRange | undefined {
  const from = parseIsoDate(startDate);
  const to = parseIsoDate(endDate);
  if (!from || !to || to < from) {
    return undefined;
  }
  return { from, to };
}

function startOfLocalDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

function toIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function parseIsoDate(value?: string | null): Date | null {
  if (!value) {
    return null;
  }
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!parts) {
    return null;
  }

  const parsed = new Date(
    Number(parts[1]),
    Number(parts[2]) - 1,
    Number(parts[3]),
  );
  if (
    parsed.getFullYear() !== Number(parts[1]) ||
    parsed.getMonth() !== Number(parts[2]) - 1 ||
    parsed.getDate() !== Number(parts[3])
  ) {
    return null;
  }
  return parsed;
}

function getSubmissionError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message.replace(/^Value error,\s*/i, "");
  }
  return "Unable to update the travel dates. Please try again.";
}

function formatSelectedDate(value: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(value);
}
