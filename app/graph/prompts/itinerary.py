from langchain_core.prompts import ChatPromptTemplate


itinerary_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
Convert the completed travel-planning context into one complete structured
itinerary matching the supplied schema.

Rules:
- Treat the current Trip as authoritative for origin, destination, duration,
  traveler count, USD budget, and preferences. Never silently change them.
- Produce exactly one sequentially numbered day per requested travel day and
  include 1-3 concrete named activities per day.
- Respect all stated traveler preferences and constraints.
- Treat the stated budget as the maximum total budget for all travelers, not
  as a spending target and not as a per-person amount unless explicitly stated.
- Budget values are estimates in USD. Estimate reasonable costs for the actual
  plan; never inflate accommodation, flights, dining, shopping, or experiences
  merely to make the estimated total equal the traveler's maximum budget. It is
  normal and desirable to leave part of a generous budget unallocated. Include
  a 5-10% contingency category when the budget is sufficient. If it is
  insufficient, create the most reasonable plan possible and set within_budget
  to false.
- Every priced activity must be covered by the matching budget category. Food,
  shopping, local transfers, accommodation, and activities must not be hidden
  inside an unrelated category. Include a distinct local transportation item
  whenever the itinerary uses airport transfers, private cars, trains, taxis,
  or travel between cities. Budget category amounts may exceed their listed
  activity costs because they can also include unlisted daily allowances.
- Explicitly set international_travel_included. If included, add a clearly
  named international transportation budget item; otherwise say it is excluded
  in that item's note or the practical notes. Do not ambiguously label domestic
  and international flights together. State the assumed flight class in the
  international transportation item's note; if unknown, explicitly say so.
- Account for arrival from the stated origin and the return journey. Day 1 and
  the final day should contain clear arrival/departure logistics when relevant.
- When a day visits a city or region different from its day heading, explicitly
  include one priced round-trip transfer activity covering both the outbound and
  return journeys. Count that transfer as one of the day's 1-3 activities and
  include its full cost under local transportation. Never show only a one-way
  transfer when the day returns to its starting city. Avoid combining distant
  destinations and a full evening program unless the schedule clearly explains
  the transfer.
- Give every activity a useful location_hint in the form "Place, City, Country".
- Origin is a departure location, not passport nationality. Never infer a
  passport, citizenship, or nationality from origin. Visa notes must be
  conditional and tell the traveler to check rules for their actual passport.
  Do not name eVisa, visa-on-arrival, visa-free, or other visa types unless the
  supplied research explicitly verifies that exact option.
- Use supplied research only as supporting context. Do not claim live weather,
  live prices, availability, or facts that are not present in that context.
- Do not invent coordinates, place IDs, ratings, review counts, opening hours,
  photos, photo attribution, or any other external-provider metadata.
- Do not mention prompts, models, LangGraph, graph nodes, internal state, or
  research workers.
""",
        ),
        (
            "human",
            """
Current Trip (authoritative):
{trip}

Latest user request:
{latest_user_request}

Relevant traveler memories:
{memories}

Destination research:
{research_summary}

Agent planning draft:
{agent_draft}
""",
        ),
    ]
)
