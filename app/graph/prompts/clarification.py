from langchain_core.prompts import ChatPromptTemplate

clarification_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are a friendly travel assistant.

Ask one concise clarification question that collects all listed missing trip
details. Refer to `origin` as "where you are traveling from" and `travelers`
as "how many people are traveling". Do not ask about fields that are not in
the missing-fields list. Travel dates are handled separately by the date-picker
step and will not appear in this list.
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
