from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.graph.state import TravelState


def unsupported_responder_node(
    state: TravelState,
    config: RunnableConfig,
) -> dict[str, object]:
    """Explain supported actions while preserving every saved travel field."""

    del state, config
    response = (
        "I can help create or modify a trip, extend its dates, suggest flights "
        "or hotels, and answer travel questions. I haven't changed your saved "
        "trip because this request isn't a supported travel action."
    )
    return {"response": response, "messages": [AIMessage(content=response)]}
