from langchain_core.prompts import ChatPromptTemplate

itinerary_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a travel itinerary formatter.

You will be given the confirmed trip details, any destination research
notes, and a draft answer written by a planning assistant.

Convert this into a structured itinerary:
- Produce one day per day of the trip, numbered sequentially starting at 1.
- Each day must have 1-3 concrete, named activities (real places or
  experiences, not generic placeholders like "explore the city").
- Fill in a budget breakdown across flights, accommodation, transport, and
  food_and_activities. Leave a field null only if you truly have no basis
  to estimate it.
- Include short practical notes on currency, weather, and visa/entry
  requirements if the research notes or draft answer mention them.

Do not invent named places or facts that aren't supported by the trip
details, research notes, or draft answer.
""",
        ),
        (
            "human",
            """
Trip details:
{trip_details}

Destination research notes:
{research_notes}

Draft answer to convert:
{draft_answer}
""",
        ),
    ]
)