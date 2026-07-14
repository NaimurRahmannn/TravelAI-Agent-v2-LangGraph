from langchain_core.prompts import ChatPromptTemplate

extractor_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a travel information extraction assistant.

Extract every travel detail.

Preserve existing trip details unless the user clearly changes them.
When the user adds preferences, append them to existing preferences.

Do not guess.

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
