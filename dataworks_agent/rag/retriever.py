"""语义检索器 — 基于向量相似度从 ChromaDB 检索相关文档片段。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """单次检索返回的单个文档片段。"""

    doc_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "content": self.content,
            "metadata": self.metadata,
            "score": round(self.score, 4),
        }


class KnowledgeRetriever:
    """从知识索引中检索与查询最相关的文档片段。"""

    def __init__(self, embedder: TextEmbedder, config: RAGConfig) -> None:  # noqa: F821
        self._embedder = embedder
        self._config = config
        self._client: Any = None
        self._collection: Any = None
        self._load_collection()

    def _load_collection(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError:
            logger.warning("chromadb not installed; retriever will use in-memory fallback")
            return

        persist_dir = self._config.persist_path
        if not persist_dir.exists():
            logger.info("ChromaDB 持久化目录不存在: %s", persist_dir)
            return
        try:
            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_collection(name=self._config.collection_name)
            logger.info(
                "ChromaDB collection '%s' loaded (documents=%d)",
                self._config.collection_name,
                self._collection.count(),
            )
        except Exception as exc:
            logger.warning("无法加载 ChromaDB 集合，将使用 fallback: %s", exc)

    async def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievalResult]:
        """按语义相似度检索文档片段。"""
        if not query or not query.strip():
            return []

        k = top_k or self._config.top_k
        threshold = self._config.score_threshold

        try:
            query_embedding = await self._embedder.embed_text(query)
        except Exception as exc:
            logger.error("查询向量化失败: %s", exc)
            return []

        results: list[RetrievalResult] = []

        if self._collection is not None:
            try:
                response = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(k * 3, 50),
                    include=["documents", "metadatas", "distances"],
                )
                docs = response.get("documents", [[]])[0] or []
                metas = response.get("metadatas", [[]])[0] or []
                distances = response.get("distances", [[]])[0] or []

                for doc, meta, distance in zip(docs, metas, distances, strict=True):
                    score = 1.0 - distance
                    if score >= threshold:
                        results.append(
                            RetrievalResult(
                                doc_id=str(meta.get("doc_id", "")),
                                content=doc,
                                metadata=meta,
                                score=score,
                            )
                        )
            except Exception as exc:
                logger.error("ChromaDB 检索失败: %s", exc)

        if not results and self._collection is None:
            results = await self._fallback_retrieve(query, query_embedding, k, threshold)

        results.sort(key=lambda r: -r.score)
        return results[:k]

    async def _fallback_retrieve(
        self,
        query: str,
        query_vec: list[float],
        top_k: int,
        threshold: float,
    ) -> list[RetrievalResult]:
        """当 ChromaDB 不可用时，基于内存中的简单 TF-IDF 检索。"""
        from dataworks_agent.rag.embedder import cosine_similarity

        results: list[RetrievalResult] = []
        for chunk_key, chunk_data in list(self._embedder._tfidf_vectors.items()):
            if chunk_key not in chunk_data:
                continue
            vec = chunk_data[chunk_key]
            score = cosine_similarity(query_vec, vec)
            if score >= threshold:
                results.append(
                    RetrievalResult(
                        doc_id=chunk_key,
                        content=chunk_key,
                        metadata={},
                        score=score,
                    )
                )
        return results[:top_k]

    async def retrieve_for_intent(self, user_message: str) -> str:
        """将检索结果拼接为意图解析上下文。"""
        results = await self.retrieve(user_message)
        if not results:
            return ""
        lines = ["## RAG 相关知识上下文"]
        for item in results:
            lines.append(f"- [{item.doc_id}] (score={item.score:.2f}): {item.content[:200]}")
        return "\n".join(lines)

    async def retrieve_for_planning(self, task_type: str, params: dict[str, Any]) -> str:
        """为任务规划生成规范上下文。"""
        query_parts = [task_type]
        for key, value in params.items():
            if isinstance(value, str) and value.strip():
                query_parts.append(f"{key}:{value}")
        query = " ".join(query_parts)
        results = await self.retrieve(query, top_k=self._config.top_k)
        if not results:
            return ""
        lines = ["## 规划参考规范"]
        for item in results:
            source = item.metadata.get("source", "unknown")
            lines.append(f"- [{source}] {item.content[:300]}")
        return "\n".join(lines)
