"""Knowledge package — GraphRAG loaded lazily."""

__all__ = ["GraphRAGService", "get_graphrag_service"]


def __getattr__(name: str):
    if name in __all__:
        from apps.knowledge.graphrag import GraphRAGService, get_graphrag_service

        return {
            "GraphRAGService": GraphRAGService,
            "get_graphrag_service": get_graphrag_service,
        }[name]
    raise AttributeError(name)
