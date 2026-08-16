"""Architecture notes for Scheme A (LangGraph multi-agent)."""

# Scheme A — LangGraph Multi-Agent
#
# Gateway (FastAPI)
#   POST /v1/chat  →  Orchestrator.chat()
#
# Orchestrator (LangGraph StateGraph)
#   START → supervisor → {order|logistics|postsale|knowledge|chitchat} → END
#   Checkpointer: memory | sqlite | postgres
#
# Specialist Agents (create_react_agent + domain tools)
#   order      → MySQL order/receive tools
#   logistics  → MySQL logistics/complaint tools
#   postsale   → MySQL postsale tools
#   knowledge  → GraphRAG (Neo4j hybrid + Text2Cypher)
#   chitchat   → LLM only
#
# Evolution path
#   Scheme B: wrap cancel/postsale writes in Temporal workflows
#   Scheme C: extract domain tools into independent microservices
