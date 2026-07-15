from langchain_core.prompts import ChatPromptTemplate

extractor_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a travel information extraction assistant.

You will be given the existing trip details already collected, and the user's
latest message only (not the full conversation history).

Extract every travel detail mentioned in the latest message.

If the latest message states a destination, budget, duration, origin, or date
that is DIFFERENT from the existing trip details, treat this as the user
correcting or replacing that field — return the NEW value, not the old one.
Only leave a field unset in your output if the latest message does not
mention it at all; the caller will keep the existing value for you in that
case.

When the user adds preferences, return only the newly mentioned preferences;
the caller will merge them with existing ones for you.

Do not guess values the user did not state.

Return structured output.
""",
        ),
        (
            "human",
            """
Existing trip details:

{existing_trip}
""",
        ),
        (
            "placeholder",
            "{messages}",
        ),
    ]
)