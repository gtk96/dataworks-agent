"""文档索引器 — 将数仓规范、SQL 模板、业务注释等向量化并存储到 ChromaDB。"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeIndexer:
    """负责文档分块、向量化与持久化存储。"""

    def __init__(self, embedder: TextEmbedder, config: RAGConfig) -> None:  # noqa: F821
        self._embedder = embedder
        self._config = config
        self._client: Any = None
        self._collection: Any = None
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError:
            logger.warning("chromadb not installed; indexer will operate in dry-run mode")
            return

        persist_dir = self._config.persist_path
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=self._config.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaDB collection '%s' ready at %s (documents=%d)",
            self._config.collection_name,
            persist_dir,
            self._collection.count(),
        )

    async def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """索引单篇文档。若已存在相同 doc_id 则更新。"""
        if not content or not content.strip():
            logger.debug("跳过空文档: %s", doc_id)
            return False

        chunks = self._chunk(content)
        if not chunks:
            return False

        meta = dict(metadata or {})
        meta.setdefault("doc_id", doc_id)
        meta.setdefault("chunk_count", len(chunks))

        try:
            ids = [f"{doc_id}::chunk_{i}" for i in range(len(chunks))]
            embeddings = await self._embedder.embed_texts([c["text"] for c in chunks])
        except Exception as exc:
            logger.error("嵌入失败，跳过文档 %s: %s", doc_id, exc)
            return False

        payload: dict[str, Any] = {
            "ids": ids,
            "documents": [c["text"] for c in chunks],
            "metadatas": [
                {
                    **meta,
                    "chunk_index": c["index"],
                    "chunk_start": c["start"],
                    "chunk_end": c["end"],
                }
                for c in chunks
            ],
        }
        if embeddings:
            payload["embeddings"] = embeddings

        try:
            if self._collection is not None:
                existing = self._collection.get(ids=ids)
                if existing and existing.get("ids"):
                    self._collection.update(**payload)
                else:
                    self._collection.add(**payload)
                logger.info("索引文档 %s: %d chunks", doc_id, len(chunks))
                return True
        except Exception as exc:
            logger.error("ChromaDB 写入失败: %s", exc)

        return False

    async def index_directory(self, directory: Path, file_pattern: str = "*.md") -> int:
        """扫描目录并按文件逐个索引。"""
        if not directory.exists():
            logger.info("索引目录不存在，跳过: %s", directory)
            return 0

        count = 0
        for path in sorted(directory.rglob(file_pattern)):
            try:
                content = path.read_text(encoding="utf-8-sig")
            except Exception as exc:
                logger.warning("读取文件失败 %s: %s", path, exc)
                continue
            if not content.strip():
                continue
            doc_id = f"file://{path.relative_to(directory.parent)}"
            if await self.index_document(doc_id, content, {"source": "file", "path": str(path)}):
                count += 1
        logger.info("目录索引完成: %s -> %d documents", directory, count)
        return count

    async def index_warehouse_specs(self) -> int:
        """索引 warehouse/ 下的 YAML 数仓规范文件。"""
        specs_dir = Path(__file__).resolve().parents[2] / "warehouse"
        if not specs_dir.exists():
            logger.info("warehouse 目录不存在，跳过规范索引")
            return 0

        count = 0
        for yaml_file in sorted(specs_dir.glob("*.yaml")):
            content = yaml_file.read_text(encoding="utf-8-sig")
            if not content.strip():
                continue
            doc_id = f"warehouse://{yaml_file.stem}"
            if await self.index_document(
                doc_id,
                content,
                {"source": "warehouse_spec", "layer": yaml_file.stem},
            ):
                count += 1
        logger.info("数仓规范索引完成: %d files", count)
        return count

    async def index_skill_documents(self) -> int:
        """索引 skills/ 目录下的 Markdown Skill 文件。"""
        skills_dir = Path(__file__).resolve().parents[2] / "dataworks_agent" / "skills"
        if not skills_dir.exists():
            logger.info("skills 目录不存在，跳过 skill 文档索引")
            return 0

        count = 0
        for md_file in sorted(skills_dir.rglob("*.md")):
            content = md_file.read_text(encoding="utf-8-sig")
            if not content.strip():
                continue
            doc_id = f"skill://{md_file.relative_to(skills_dir.parent)}"
            if await self.index_document(
                doc_id, content, {"source": "skill", "path": str(md_file)}
            ):
                count += 1
        logger.info("Skill 文档索引完成: %d files", count)
        return count

    async def rebuild_index(self) -> int:
        """重建索引：清空集合后重新索引所有默认来源。"""
        try:
            if self._collection is not None:
                self._collection.delete(where={})
                logger.info("已清空集合 %s", self._config.collection_name)
        except Exception as exc:
            logger.warning("清空集合失败（可能集合不存在）: %s", exc)

        total = 0
        total += await self.index_warehouse_specs()
        total += await self.index_skill_documents()
        for source_dir in self._config.source_dirs:
            dir_path = Path(source_dir)
            if dir_path.exists():
                total += await self.index_directory(dir_path)
        logger.info("RAG 索引重建完成，总计 %d documents", total)
        return total

    @staticmethod
    def _chunk(
        text: str, *, chunk_size: int | None = None, overlap: int | None = None
    ) -> list[dict[str, Any]]:
        """按标题/段落分块。"""
        size = chunk_size or 500
        step = max(1, (size - (overlap or 100)))
        paragraphs = re.split(r"\n\s*\n+", text.strip())
        chunks: list[dict[str, Any]] = []
        buffer = ""
        start_offset = 0
        idx = 0

        for paragraph in paragraphs:
            para = paragraph.strip()
            if not para:
                continue
            if len(buffer) + len(para) + 2 <= size:
                buffer = f"{buffer}\n\n{para}" if buffer else para
            else:
                if buffer:
                    chunks.append(
                        {
                            "index": idx,
                            "text": buffer.strip(),
                            "start": start_offset,
                            "end": start_offset + len(buffer),
                        }
                    )
                    idx += 1
                    overlap_text = buffer[-step:] if step > 0 and len(buffer) > step else ""
                    buffer = f"{overlap_text}\n\n{para}".strip() if overlap_text else para
                    start_offset += len(buffer) - len(para)
                else:
                    buffer = para
                    start_offset = start_offset + sum(len(p) + 2 for p in paragraphs[:idx])

        if buffer:
            chunks.append(
                {
                    "index": idx,
                    "text": buffer.strip(),
                    "start": start_offset,
                    "end": start_offset + len(buffer),
                }
            )

        return chunks
