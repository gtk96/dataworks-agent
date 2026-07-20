"""嵌入模型封装 — 支持本地 sentence-transformers / OpenAI API / fallback。"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """嵌入请求失败时抛出。"""


class TextEmbedder:
    """统一嵌入接口，优先使用本地模型，不可用时回退到 OpenAI 或 TF-IDF。"""

    def __init__(self, config: RAGConfig) -> None:  # noqa: F821
        self._config = config
        self._provider: str | None = None
        self._model: Any = None
        self._openai_client: Any = None
        self._tfidf_vectors: dict[str, dict[str, float]] = {}
        self._initialize()

    def _initialize(self) -> None:
        if os.environ.get("OPENAI_API_KEY"):
            try:
                from openai import AsyncOpenAI

                self._openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
                self._provider = "openai"
                logger.info("RAG embedder provider=openai model=%s", self._config.embedding_model)
                return
            except Exception as exc:
                logger.warning("OpenAI embedder init failed: %s", exc)

        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._config.embedding_model)
            self._provider = "sentence_transformers"
            logger.info(
                "RAG embedder provider=sentence_transformers model=%s",
                self._config.embedding_model,
            )
            return
        except Exception as exc:
            logger.warning("sentence-transformers unavailable (%s), falling back to tfidf", exc)

        self._provider = "tfidf"
        logger.info("RAG embedder provider=tfidf (fallback)")

    async def embed_text(self, text: str) -> list[float]:
        """将单条文本向量化。"""
        if not text or not text.strip():
            return self._zero_vector(384)
        if self._provider == "sentence_transformers":
            return self._embed_local([text])[0]
        if self._provider == "openai" and self._openai_client is not None:
            return await self._embed_openai([text])
        return self._embed_tfidf([text])[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量向量化。"""
        if not texts:
            return []
        cleaned = [t.strip() for t in texts]
        if self._provider == "sentence_transformers":
            return self._embed_local(cleaned)
        if self._provider == "openai" and self._openai_client is not None:
            return await self._embed_openai_batch(cleaned)
        return self._embed_tfidf(cleaned)

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        assert self._model is not None
        embeddings = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return [vec.tolist() for vec in embeddings]

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        assert self._openai_client is not None
        response = await self._openai_client.embeddings.create(
            input=texts,
            model=self._config.embedding_model,
        )
        return [item.embedding for item in response.data]

    async def _embed_openai_batch(self, texts: list[str]) -> list[list[float]]:
        assert self._openai_client is not None
        results: list[list[float]] = []
        for i in range(0, len(texts), self._config.max_batch_size):
            batch = texts[i : i + self._config.max_batch_size]
            response = await self._openai_client.embeddings.create(
                input=batch,
                model=self._config.embedding_model,
            )
            results.extend(item.embedding for item in response.data)
        return results

    def _embed_tfidf(self, texts: list[str]) -> list[list[float]]:
        """基于词频的轻量 fallback，维度固定 384。"""
        vectors: list[list[float]] = []
        for text in texts:
            tokens = self._tokenize(text)
            counts: dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
            vec = [0.0] * 384
            for _idx, (token, count) in enumerate(counts.items()):
                bucket = hash(token) % 384
                vec[bucket] += count / norm
            vectors.append(vec)
        return vectors

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [t.lower() for t in text.split() if t.strip()]

    @staticmethod
    def _zero_vector(dim: int = 384) -> list[float]:
        return [0.0] * dim


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1e-9
    norm_b = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (norm_a * norm_b)


def fingerprint(content: str) -> str:
    """为文档内容生成稳定短标识，用于去重。"""
    return "f_" + hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:16]
