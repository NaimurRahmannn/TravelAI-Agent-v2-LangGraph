from langchain_core.prompts import ChatPromptTemplate

clarification_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a friendly travel assistant.

Ask exactly one concise clarification question that helps collect
the missing trip details.
""",
        ),
        (
            "human",
            """
Missing fields:

{missing_fields}
""",
        ),
    ]
)
