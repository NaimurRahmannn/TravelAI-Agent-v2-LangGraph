from app.graph.state import TravelState
from langchain_core.runnables import RunnableConfig

def planner_node(state: TravelState,
                 config: RunnableConfig):
    print("Planner node executed")
    return{
        "planner":{
            "current_step":"Planning",
            "next_action":"finish"
        }
    }