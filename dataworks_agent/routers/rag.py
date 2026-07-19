"""RAG 知识检索 API 路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["RAG"])


@router.post("/rag/rebuild")
async def rebuild_rag_index() -> dict:
    """手动触发 RAG 索引重建。"""
    try:
        from dataworks_agent.rag.config import RAGConfig
        from dataworks_agent.rag.embedder import TextEmbedder
        from dataworks_agent.rag.indexer import KnowledgeIndexer

        config = RAGConfig()
        embedder = TextEmbedder(config)
        indexer = KnowledgeIndexer(embedder, config)
        count = await indexer.rebuild_index()

        return {
            "success": True,
            "message": f"RAG 索引重建完成，共索引 {count} 个文档",
            "document_count": count,
        }
    except Exception as exc:
        logger.exception("RAG 索引重建失败")
        raise HTTPException(status_code=500, detail=f"索引重建失败：{exc!s}") from exc


@router.get("/rag/status")
async def rag_status() -> dict:
    """查看 RAG 索引状态。"""
    try:
        from dataworks_agent.rag.config import RAGConfig
        from dataworks_agent.rag.embedder import TextEmbedder
        from dataworks_agent.rag.retriever import KnowledgeRetriever

        config = RAGConfig()
        embedder = TextEmbedder(config)
        retriever = KnowledgeRetriever(embedder, config)

        collection_count = retriever._collection.count() if retriever._collection else 0

        return {
            "success": True,
            "collection_name": config.collection_name,
            "document_count": collection_count,
            "persist_dir": str(config.persist_path),
            "embedding_model": config.embedding_model,
        }
    except Exception as exc:
        logger.exception("获取 RAG 状态失败")
        raise HTTPException(status_code=500, detail=f"获取状态失败：{exc!s}") from exc


@router.post("/rag/query")
async def rag_query(query: str, top_k: int = 5) -> dict:
    """基于 RAG 知识库回答问题。"""
    try:
        from dataworks_agent.rag.config import RAGConfig
        from dataworks_agent.rag.context_provider import RAGContextProvider
        from dataworks_agent.rag.embedder import TextEmbedder
        from dataworks_agent.rag.retriever import KnowledgeRetriever

        config = RAGConfig(top_k=top_k)
        embedder = TextEmbedder(config)
        retriever = KnowledgeRetriever(embedder, config)
        provider = RAGContextProvider(retriever)

        answer = await provider.answer_question(query)

        return {
            "success": True,
            "query": query,
            "answer": answer,
        }
    except Exception as exc:
        logger.exception("RAG 查询失败")
        raise HTTPException(status_code=500, detail=f"查询失败：{exc!s}") from exc
