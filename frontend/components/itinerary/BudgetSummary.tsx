import { BadgeCheck, CircleAlert, ReceiptText } from "lucide-react";
import type { BudgetBreakdown } from "@/lib/api";
import { formatUsd } from "./formatters";

type BudgetSummaryProps = {
  budget: BudgetBreakdown;
  idPrefix: string;
};

export function BudgetSummary({ budget, idPrefix }: BudgetSummaryProps) {
  const headingId = `${idPrefix}-budget-heading`;

  return (
    <section aria-labelledby={headingId} className="budgetSummary">
      <header className="sectionHeading">
        <span>
          <ReceiptText aria-hidden="true" size={18} />
        </span>
        <div>
          <p>Plan finances</p>
          <h3 id={headingId}>Budget summary</h3>
        </div>
      </header>

      <dl className="budgetRows">
        {budget.items.map((item, index) => (
          <div key={`${item.category}-${index}`}>
            <dt>
              <span>{item.category}</span>
              {item.note ? <small>{item.note}</small> : null}
            </dt>
            <dd>{formatUsd(item.amount_usd)}</dd>
          </div>
        ))}
      </dl>

      <dl className="budgetTotals">
        <div>
          <dt>Estimated total</dt>
          <dd>{formatUsd(budget.estimated_total_usd)}</dd>
        </div>
        {budget.user_budget_usd != null ? (
          <div>
            <dt>Traveler budget</dt>
            <dd>{formatUsd(budget.user_budget_usd)}</dd>
          </div>
        ) : null}
      </dl>

      {budget.within_budget != null ? (
        <p
          className="budgetStatus"
          data-status={budget.within_budget ? "within" : "over"}
        >
          {budget.within_budget ? (
            <BadgeCheck aria-hidden="true" size={18} />
          ) : (
            <CircleAlert aria-hidden="true" size={18} />
          )}
          {budget.within_budget
            ? "Estimated plan is within your budget."
            : "Estimated plan exceeds the current budget."}
        </p>
      ) : null}
    </section>
  );
}
