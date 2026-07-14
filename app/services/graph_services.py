from langchain_core.messages import HumanMessage

from app.graph.builder import graph


class GraphService:

    def invoke(
        self,
        message: str,
    ):

        result = graph.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=message,
                    )
                ]
            }
        )

        return result["response"]