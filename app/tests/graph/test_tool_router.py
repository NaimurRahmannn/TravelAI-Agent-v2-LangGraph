from langchain_core.messages import AIMessage

from app.graph.routers.tool_router import tool_router


def test_agent_tool_call_routes_to_existing_approval_flow():
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "book_hotel",
                        "args": {},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }

    assert tool_router(state) == "approval_gate"


def test_agent_final_message_routes_to_structured_generator():
    state = {"messages": [AIMessage(content="Complete planning draft.")]}

    assert tool_router(state) == "itinerary_generator"
