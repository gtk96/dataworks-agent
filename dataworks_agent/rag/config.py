"""RAG 配置模型。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class RAGConfig(BaseModel):
    """RAG 模块配置。"""

    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="本地 sentence-transformers 嵌入模型名称",
    )
    chroma_persist_dir: str = Field(
        default="data/rag_chroma",
        description="ChromaDB 持久化目录",
    )
    collection_name: str = Field(
        default="dataworks_knowledge",
        description="ChromaDB 集合名",
    )
    top_k: int = Field(default=5, ge=1, le=20, description="检索返回最大数量")
    score_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="相似度阈值",
    )
    chunk_size: int = Field(
        default=800,
        ge=200,
        le=2000,
        description="分块大小（字符数）",
    )
    chunk_overlap: int = Field(
        default=100,
        ge=0,
        le=200,
        description="分块重叠字符数",
    )
    max_batch_size: int = Field(
        default=32,
        ge=1,
        le=128,
        description="批量嵌入时的单次最大条数",
    )
    source_dirs: list[str] = Field(
        default_factory=lambda: [
            "warehouse",
            "docs",
            "dataworks_agent/skills",
        ],
        description="索引扫描的相对目录列表",
    )

    @property
    def persist_path(self) -> Path:
        return Path(self.chroma_persist_dir)
