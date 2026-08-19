"use client";

import { DayPicker, type DateRange } from "@daypicker/react";
import { ArrowRight, CalendarDays, Loader2 } from "lucide-react";
import { FormEvent, useState } from "react";

const MAX_TRIP_DURATION_DAYS = 365;

type TravelDatePickerProps = {
  disabled?: boolean;
  onContinue: (startDate: string, endDate: string) => Promise<void> | void;
};

export function TravelDatePicker({
  disabled = false,
  onContinue,
}: TravelDatePickerProps) {
  const [selected, setSelected] = useState<DateRange>();
  const today = startOfLocalDay(new Date());
  const isComplete = selected?.from !== undefined && selected.to !== undefined;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected?.from || !selected.to || disabled) {
      return;
    }

    await onContinue(toIsoDate(selected.from), toIsoDate(selected.to));
  }

  return (
    <form className="travelDatePicker" onSubmit={handleSubmit}>
      <div className="datePickerHeading">
        <span className="datePickerIcon" aria-hidden="true">
          <CalendarDays size={19} />
        </span>
        <div>
          <h3>When are you traveling?</h3>
          <p>Select your arrival and departure dates.</p>
        </div>
      </div>

      <DayPicker
        className="travelCalendar"
        defaultMonth={today}
        disabled={{ before: today }}
        excludeDisabled
        max={MAX_TRIP_DURATION_DAYS - 1}
        mode="range"
        navLayout="after"
        onSelect={setSelected}
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

      <button
        className="datePickerContinue"
        disabled={!isComplete || disabled}
        type="submit"
      >
        {disabled ? <Loader2 className="spin" size={17} /> : null}
        Continue
      </button>
    </form>
  );
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

function formatSelectedDate(value: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(value);
}
