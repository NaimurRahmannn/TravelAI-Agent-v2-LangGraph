from app.graph.state import TravelState

def planner_node(state: TravelState):
    print("Planner node executed")
    return{
        "planner":{
            "current_step":"Planning",
            "next_action":"finish"
        }
    }