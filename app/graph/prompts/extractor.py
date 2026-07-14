from langchain_core.prompts import ChatPromptTemplate

extractor_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a travel information extraction assistant.

Extract every travel detail.

Do not guess.

Return structured output.
""",
        ),
        (
            "placeholder",
            "{messages}",
        ),
    ]
)