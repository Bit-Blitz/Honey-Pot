from langgraph.graph import StateGraph, END
from app.engine.nodes import (
    AgentState, load_history, detect_scam, 
    extract_intel, save_state, finalize_report
)

def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("load_history", load_history)
    workflow.add_node("process_interaction", detect_scam) # Detection + Persona Response
    workflow.add_node("extract_forensics", extract_intel)
    workflow.add_node("generate_takedown_report", finalize_report)
    workflow.add_node("persist_state", save_state)

    workflow.set_entry_point("load_history")
    
    workflow.add_edge("load_history", "process_interaction")
    workflow.add_edge("process_interaction", "extract_forensics")
    workflow.add_edge("extract_forensics", "generate_takedown_report")
    workflow.add_edge("generate_takedown_report", "persist_state")
    workflow.add_edge("persist_state", END)

    return workflow.compile()

app_graph = build_graph()