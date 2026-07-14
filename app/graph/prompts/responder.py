from langchain_core.prompts import ChatPromptTemplate

responder_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a helpful travel assistant.

Generate a concise response
based on the extracted trip.
""",
        ),
        (
            "human",
            """
Trip

{trip}
""",
        ),
    ]
)