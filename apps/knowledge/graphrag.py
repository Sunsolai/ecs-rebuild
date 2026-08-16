"""GraphRAG knowledge retrieval — Rasa-free port of EnterpriseSearch GraphRAG."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

import jieba
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.chains.graph_qa.cypher import CypherQueryCorrector, Schema
from langchain_community.graphs.neo4j_graph import Neo4jGraph
from langchain_core.embeddings import Embeddings
from langchain_core.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from neo4j import GraphDatabase
from neo4j.exceptions import CypherSyntaxError
from neo4j_graphrag.retrievers import HybridRetriever
from neo4j_graphrag.retrievers.text2cypher import extract_cypher
from pydantic import BaseModel, Field

from packages.shared.config import get_settings

logger = logging.getLogger("ecs.knowledge.graphrag")


class RouteItem(BaseModel):
    label: str = Field(..., description="节点类型，比如 SKU")
    entity: str = Field(..., description="实体文本")


class RouteOutput(BaseModel):
    outputs: list[RouteItem]


OPTIONAL_LABEL = (
    "- Category1:   一级分类\n"
    "- Category2:   二级分类\n"
    "- Category3:   三级分类\n"
    "- Trademark:   品牌\n"
    "- SPU:         商品名称\n"
    "- SKU:         单品名称\n"
    "- Attr:        商品属性值\n"
    "- User:        用户ID\n"
)


class GraphRAGService:
    """Hybrid retrieval + Text2Cypher over Neo4j product graph."""

    def __init__(self, embeddings: Embeddings):
        self.embeddings = embeddings
        self.settings = get_settings()
        self.driver = None
        self.neo4j_schema = ""
        self.cypher_corrector: Optional[CypherQueryCorrector] = None
        self.llm: Optional[ChatTongyi] = None
        self._connected = False

        self.route_label_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    "你是一个智能检索路由Agent。"
                    "根据用户输入判断最可能需要的一个或多个标签以及每个标签对应的实体，"
                    "作为后续Neo4j查询的入口节点。\n"
                    "**注意：如果查询与用户相关，需要将用户信息加入入口节点**\n"
                    '以严格JSON格式输出，例如[{{"label": "SPU", "entity": "iPhone 16 Pro"}}]。'
                    "可选节点类型:\n{optional_label}"
                ),
                HumanMessagePromptTemplate.from_template("{query}"),
            ]
        )
        self.generate_cypher_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    "你是一个Cypher专家，根据入口节点和用户输入，参照schema生成准确Cypher。"
                    "**注意：查询结果中不可以包含嵌入向量等多余属性**\n"
                    "仅返回Cypher语句。\nschema:\n{schema}"
                ),
                HumanMessagePromptTemplate.from_template(
                    "入口节点:\n{entry_nodes}\n\n用户输入:\n{query}\n\nCypher语句:"
                ),
            ]
        )
        self.validate_cypher_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    "你是一位Cypher专家，审查Cypher语句。"
                    "检查语法、关系方向、变量定义、是否满足用户意图。"
                    '以严格列表格式输出错误，例如["错误1"]；无问题返回[]。\n'
                    "schema:\n{schema}"
                ),
                HumanMessagePromptTemplate.from_template(
                    "入口节点:\n{entry_nodes}\n\n用户输入:\n{query}\n\n"
                    "待验证的Cypher语句:\n{cypher}"
                ),
            ]
        )
        self.correct_cypher_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    "你是一位Cypher专家，根据错误信息更正Cypher语句。仅返回Cypher。\n"
                    "schema:\n{schema}"
                ),
                HumanMessagePromptTemplate.from_template(
                    "入口节点:\n{entry_nodes}\n\n用户输入:\n{query}\n\n"
                    "错误信息:\n{errors}\n\n待更正的Cypher:\n{cypher}\n\n更正后:"
                ),
            ]
        )

    def connect(self) -> None:
        if self._connected:
            return
        s = self.settings
        auth = (s.neo4j_user, s.neo4j_password)
        self.driver = GraphDatabase.driver(s.neo4j_url, auth=auth)
        graph = Neo4jGraph(
            s.neo4j_url, s.neo4j_user, s.neo4j_password, enhanced_schema=True
        )
        self.neo4j_schema = graph.schema
        corrector_schema = [
            Schema(el["start"], el["type"], el["end"])
            for el in graph.structured_schema.get("relationships", [])
        ]
        self.cypher_corrector = CypherQueryCorrector(corrector_schema)
        self.llm = ChatTongyi(model=s.coder_model, api_key=s.api_key)
        self._connected = True
        logger.info("GraphRAG connected to %s", s.neo4j_url)

    async def route_label(self, query: str) -> list[RouteItem]:
        prompt = self.route_label_prompt.format_prompt(
            optional_label=OPTIONAL_LABEL, query=query
        )
        try:
            out = await self.llm.with_structured_output(RouteOutput).ainvoke(prompt)
            return out.outputs
        except Exception:
            raw = await self.llm.ainvoke(prompt)
            data = json.loads(raw.content)
            return [RouteItem(**item) for item in data]

    async def node_retrieval(self, route_res: list[RouteItem], top_k: int) -> dict:
        pairs = []
        retrieved: dict[str, list] = {}
        for item in route_res:
            if not item.entity:
                continue
            if item.label == "User":
                user_node = self.driver.execute_query(
                    "match (u:User) where u.user_id = $user_id return u;",
                    {"user_id": int(item.entity)},
                )
                retrieved.setdefault(item.label, []).append(user_node)
            else:
                pairs.append((item.label, item.entity))

        if not pairs:
            return retrieved

        labels, entities = zip(*pairs)
        query_texts = [
            " OR ".join(
                w.strip()
                for w in jieba.lcut(entity)
                if re.fullmatch(r"[a-zA-Z0-9\u4e00-\u9fa5]+", w.strip())
            )
            for entity in entities
        ]
        query_vectors = self.embeddings.embed_documents(list(entities))

        tasks = []
        for label, query_text, query_vector in zip(labels, query_texts, query_vectors):
            retriever = HybridRetriever(
                self.driver,
                vector_index_name=label.lower() + "_vector",
                fulltext_index_name=label.lower() + "_fulltext",
            )
            tasks.append(
                asyncio.to_thread(
                    retriever.get_search_results,
                    query_text,
                    query_vector,
                    top_k,
                    effective_search_ratio=2,
                )
            )
        results = await asyncio.gather(*tasks)

        for (label, _), result in zip(pairs, results):
            key = f"{label.lower()}_value" if label == "Attr" else f"{label.lower()}_name"
            retrieved.setdefault(label, []).extend(
                [{key: rec["node"][key], "score": rec["score"]} for rec in result.records]
            )
        return retrieved

    async def generate_cypher(self, query: str, entry_nodes: Any) -> str:
        prompt = self.generate_cypher_prompt.format_prompt(
            schema=self.neo4j_schema, query=query, entry_nodes=entry_nodes
        )
        out = await self.llm.ainvoke(prompt)
        return extract_cypher(out.content)

    async def validate_cypher(self, query: str, entry_nodes: Any, cypher: str) -> list:
        errors: list = []
        try:
            self.driver.execute_query(f"explain {cypher}")
        except CypherSyntaxError as e:
            errors.append(str(e))
        prompt = self.validate_cypher_prompt.format_prompt(
            schema=self.neo4j_schema,
            query=query,
            cypher=cypher,
            entry_nodes=entry_nodes,
        )
        out = await self.llm.ainvoke(prompt)
        try:
            errors.extend(json.loads(out.content))
        except Exception:
            if out.content.strip():
                errors.append(out.content.strip())
        return errors

    async def correct_cypher(
        self, query: str, entry_nodes: Any, cypher: str, errors: list
    ) -> str:
        prompt = self.correct_cypher_prompt.format_prompt(
            schema=self.neo4j_schema,
            query=query,
            cypher=cypher,
            entry_nodes=entry_nodes,
            errors=errors,
        )
        out = await self.llm.ainvoke(prompt)
        return extract_cypher(out.content)

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        chat_history: Optional[str] = None,
    ) -> dict[str, Any]:
        self.connect()
        query = (query or "").strip()
        if not query:
            return {"ok": False, "message": "查询为空", "documents": []}

        history = chat_history or query
        if user_id:
            history = f"user_id={user_id}\n{history}"

        route_res = await self.route_label(history)
        entry_nodes = await self.node_retrieval(
            route_res, self.settings.knowledge_top_k
        )
        cypher = await self.generate_cypher(query, entry_nodes)
        errors = await self.validate_cypher(query, entry_nodes, cypher)
        if errors:
            cypher = await self.correct_cypher(query, entry_nodes, cypher, errors)
        cypher = self.cypher_corrector(cypher) if self.cypher_corrector else cypher

        docs: list[str] = []
        try:
            records = self.driver.execute_query(cypher).records
            docs = [str(dict(rec)) for rec in records]
        except Exception as e:
            logger.warning("Cypher execution failed: %s", e)
            return {
                "ok": False,
                "message": f"图谱查询失败: {e}",
                "cypher": cypher,
                "documents": [],
            }

        return {
            "ok": True,
            "cypher": cypher,
            "entry_nodes": entry_nodes,
            "documents": docs or ["未检索到相关商品信息"],
        }


_service: Optional[GraphRAGService] = None


def get_graphrag_service() -> GraphRAGService:
    global _service
    if _service is None:
        from apps.knowledge.embeddings import build_embeddings

        _service = GraphRAGService(build_embeddings())
    return _service
