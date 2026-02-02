from langgraph.graph import StateGraph, END
from app.engine.nodes import (
    AgentState, load_history, detect_scam, 
    generate_response, extract_intel, save_state
)

def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("load_history", load_history)
    workflow.add_node("detect_scam", detect_scam)
    workflow.add_node("generate_response", generate_response)
    workflow.add_node("extract_intel", extract_intel)
    workflow.add_node("save_state", save_state)

    workflow.set_entry_point("load_history")
    
    workflow.add_edge("load_history", "detect_scam")
    workflow.add_edge("detect_scam", "generate_response")
    workflow.add_edge("generate_response", "extract_intel")
    workflow.add_edge("extract_intel", "save_state")
    workflow.add_edge("save_state", END)

    return workflow.compile()

app_graph = build_graph()