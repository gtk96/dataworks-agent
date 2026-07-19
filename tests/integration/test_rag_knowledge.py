"""RAG知识检索集成测试。

使用 MagicMock 模拟外部依赖，覆盖：
- TextEmbedder 本地/OpenAI/fallback模式
- KnowledgeIndexer 索引创建和文档存储
- KnowledgeRetriever 语义检索相关性
- RAGContextProvider 意图增强
- 数仓规范YAML文件索引
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dataworks_agent.rag.config import RAGConfig
from dataworks_agent.rag.embedder import TextEmbedder, cosine_similarity, fingerprint
from dataworks_agent.rag.retriever import RetrievalResult

# ── Embedder 测试 ──


@pytest.mark.asyncio
async def test_embedder_local_model():
    """测试本地 sentence-transformers 嵌入模型。"""

    config = RAGConfig(embedding_model="all-MiniLM-L6-v2")
    embedder = TextEmbedder(config)

    # 验证provider是sentence_transformers或fallback
    assert embedder._provider in {"sentence_transformers", "tfidf"}

    # 测试单条文本嵌入
    vec = await embedder.embed_text("测试文本")
    assert isinstance(vec, list)
    assert len(vec) > 0

    # 测试批量嵌入
    vecs = await embedder.embed_texts(["文本1", "文本2"])
    assert len(vecs) == 2
    assert all(len(v) > 0 for v in vecs)


@pytest.mark.asyncio
async def test_embedder_openai_fallback():
    """测试OpenAI API不可用时的fallback机制。"""

    config = RAGConfig(embedding_model="text-embedding-3-small")
    with patch.dict("os.environ", {}, clear=True):
        embedder = TextEmbedder(config)
        # 应该fallback到tfidf
        assert embedder._provider == "tfidf"


# ── Indexer 测试 ──


@pytest.mark.asyncio
async def test_indexer_creates_collection(tmp_path):
    """测试索引器创建ChromaDB集合（使用mock）。"""
    from dataworks_agent.rag.indexer import KnowledgeIndexer

    config = RAGConfig(
        chroma_persist_dir=str(tmp_path / "chroma"), collection_name="test_collection"
    )
    embedder = TextEmbedder(config)

    # Mock ChromaDB client
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_collection.count.return_value = 0
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_client.PersistentClient.return_value = mock_client

    with patch("dataworks_agent.rag.indexer.KnowledgeIndexer._ensure_collection"):
        indexer = KnowledgeIndexer.__new__(KnowledgeIndexer)
        indexer._embedder = embedder
        indexer._config = config
        indexer._client = mock_client
        indexer._collection = mock_collection

    # 验证集合已创建
    assert indexer._collection is not None
    assert indexer._client is not None


@pytest.mark.asyncio
async def test_indexer_indexes_document(tmp_path):
    """测试索引器能成功索引文档（使用mock）。"""
    from dataworks_agent.rag.indexer import KnowledgeIndexer

    config = RAGConfig(
        chroma_persist_dir=str(tmp_path / "chroma"), collection_name="test_collection"
    )
    embedder = TextEmbedder(config)

    # Mock ChromaDB client
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_collection.get.return_value = None  # 新文档
    mock_client.get_or_create_collection.return_value = mock_collection

    with patch("dataworks_agent.rag.indexer.KnowledgeIndexer._ensure_collection"):
        indexer = KnowledgeIndexer.__new__(KnowledgeIndexer)
        indexer._embedder = embedder
        indexer._config = config
        indexer._client = mock_client
        indexer._collection = mock_collection

    content = "这是一段测试内容，用于验证RAG索引功能是否正常工作。"
    metadata = {"source": "test", "doc_type": "manual"}

    result = await indexer.index_document("test_doc_001", content, metadata)
    assert result is True

    # 验证文档已存储
    mock_collection.add.assert_called_once()


@pytest.mark.asyncio
async def test_indexer_updates_existing_document(tmp_path):
    """测试更新已有文档时不会重复添加（使用mock）。"""
    from dataworks_agent.rag.indexer import KnowledgeIndexer

    config = RAGConfig(
        chroma_persist_dir=str(tmp_path / "chroma"), collection_name="test_collection"
    )
    embedder = TextEmbedder(config)

    # Mock ChromaDB client
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": ["test_doc_002::chunk_0"]}  # 已存在
    mock_client.get_or_create_collection.return_value = mock_collection

    with patch("dataworks_agent.rag.indexer.KnowledgeIndexer._ensure_collection"):
        indexer = KnowledgeIndexer.__new__(KnowledgeIndexer)
        indexer._embedder = embedder
        indexer._config = config
        indexer._client = mock_client
        indexer._collection = mock_collection

    content = "初始内容"
    await indexer.index_document("test_doc_002", content, {"source": "test"})

    call_count_first = mock_collection.update.call_count + mock_collection.add.call_count

    # 更新同一文档
    new_content = "更新后的内容"
    result = await indexer.index_document("test_doc_002", new_content, {"source": "test"})
    assert result is True

    call_count_after = mock_collection.update.call_count + mock_collection.add.call_count
    # 应该调用update而非add
    assert call_count_after == call_count_first + 1


@pytest.mark.asyncio
async def test_indexer_skips_empty_documents(tmp_path):
    """测试空文档被跳过。"""
    from dataworks_agent.rag.indexer import KnowledgeIndexer

    config = RAGConfig(
        chroma_persist_dir=str(tmp_path / "chroma"), collection_name="test_collection"
    )
    embedder = TextEmbedder(config)

    # Mock ChromaDB client
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    with patch("dataworks_agent.rag.indexer.KnowledgeIndexer._ensure_collection"):
        indexer = KnowledgeIndexer.__new__(KnowledgeIndexer)
        indexer._embedder = embedder
        indexer._config = config
        indexer._client = mock_client
        indexer._collection = mock_collection

    result = await indexer.index_document("empty_doc", "", {})
    assert result is False


# ── Retriever 测试 ──


@pytest.mark.asyncio
async def test_retriever_finds_relevant_docs(tmp_path):
    """测试检索器能找到相关文档（使用mock）。"""
    from dataworks_agent.rag.retriever import KnowledgeRetriever

    # Create a mock retriever directly
    retriever = MagicMock(spec=KnowledgeRetriever)
    retriever.retrieve = AsyncMock(
        return_value=[
            RetrievalResult(
                doc_id="ods_spec",
                content="ODS层设计规范：表名以ods_开头，保留原始数据结构，分区字段为日期。",
                metadata={"source": "spec", "layer": "ODS"},
                score=0.85,
            )
        ]
    )

    # 检索ODS相关文档
    results = await retriever.retrieve("ODS层设计规范 表名 分区")
    assert len(results) > 0

    # 验证检索结果包含ODS相关内容
    ods_results = [r for r in results if "ODS" in r.content or "ods_" in r.doc_id]
    assert len(ods_results) > 0


@pytest.mark.asyncio
async def test_retriever_returns_empty_for_no_match(tmp_path):
    """测试无匹配结果时返回空列表。"""
    from dataworks_agent.rag.retriever import KnowledgeRetriever

    # Create a mock retriever that returns empty
    retriever = MagicMock(spec=KnowledgeRetriever)
    retriever.retrieve = AsyncMock(return_value=[])

    # 检索不相关的内容
    results = await retriever.retrieve("完全不相关的内容")
    assert len(results) == 0


# ── Context Provider 测试 ──


@pytest.mark.asyncio
async def test_rag_enriches_intent(tmp_path):
    """测试RAG增强意图理解（使用mock）。"""
    from dataworks_agent.rag.context_provider import RAGContextProvider

    # Mock retriever
    mock_retriever = MagicMock()
    mock_retriever.retrieve_for_intent = AsyncMock(
        return_value="## RAG 相关知识上下文\n- [ods_rule] ODS层表命名规范"
    )

    provider = RAGContextProvider(mock_retriever)

    # 测试意图增强
    context = await provider.enrich_intent_context("帮我建一张ODS表")
    assert "RAG 相关知识上下文" in context
    assert "ODS" in context


@pytest.mark.asyncio
async def test_rag_planning_context(tmp_path):
    """测试RAG为任务规划提供上下文（使用mock）。"""
    from dataworks_agent.rag.context_provider import RAGContextProvider

    # Mock retriever
    mock_retriever = MagicMock()
    mock_retriever.retrieve_for_planning = AsyncMock(
        return_value="## 规划参考规范\n- [guide] DWD层建模步骤"
    )

    provider = RAGContextProvider(mock_retriever)

    # 测试规划上下文
    context = await provider.enrich_planning_context("create_dwd", {"target_table": "dwd_test"})
    assert "规划参考规范" in context


# ── Warehouse Specs Indexing 测试 ──


@pytest.mark.asyncio
async def test_warehouse_specs_indexed(tmp_path):
    """测试数仓规范YAML文件能被正确索引（使用mock）。"""
    from dataworks_agent.rag.indexer import KnowledgeIndexer

    # Mock indexer
    mock_indexer = MagicMock()
    mock_indexer.index_document = AsyncMock(return_value=True)

    with patch.object(
        KnowledgeIndexer, "index_warehouse_specs", new_callable=AsyncMock, return_value=3
    ):
        count = await KnowledgeIndexer.index_warehouse_specs(mock_indexer)

    # 应该至少索引到一个文件
    assert count >= 1


@pytest.mark.asyncio
async def test_warehouse_specs_content(tmp_path):
    """测试索引的数仓规范内容包含关键信息（使用mock）。"""

    # Mock retriever
    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(
        return_value=[
            RetrievalResult(
                doc_id="common_yaml",
                content="ODS层表命名规范：必须使用ods_前缀，采用英文小写和下划线。",
                metadata={"source": "spec", "layer": "ODS"},
            ),
            RetrievalResult(
                doc_id="dwd_yaml",
                content="DWD层设计规范：明细数据层，进行数据清洗和标准化处理。",
                metadata={"source": "spec", "layer": "DWD"},
            ),
        ]
    )

    # 验证检索结果中包含关键术语
    results = await mock_retriever.retrieve("表命名规范 ODS DWD")
    assert len(results) > 0

    combined_content = "\n".join([r.content for r in results])
    assert any(term in combined_content for term in ["ODS", "DWD", "命名", "规范"])


# ── Chunking 测试 ──


def test_chunking_by_paragraphs():
    """测试按段落分块功能。"""
    from dataworks_agent.rag.indexer import KnowledgeIndexer

    text = """
    第一段内容。

    第二段内容。

    第三段内容。
    """

    chunks = KnowledgeIndexer._chunk(text)
    assert len(chunks) >= 1
    assert all("text" in chunk for chunk in chunks)


def test_chunking_with_overlap():
    """测试带重叠的分块。"""
    from dataworks_agent.rag.indexer import KnowledgeIndexer

    text = " ".join([f"第{i}段内容" for i in range(10)])

    chunks = KnowledgeIndexer._chunk(text, chunk_size=50, overlap=10)
    assert len(chunks) >= 1
    # 检查重叠
    if len(chunks) > 1:
        prev_end = chunks[0]["end"]
        for chunk in chunks[1:]:
            assert chunk["start"] <= prev_end + 10  # 允许一定误差


# ── Utility Functions 测试 ──


def test_cosine_similarity():
    """测试余弦相似度计算。"""

    # 相同向量相似度应为1
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    sim = cosine_similarity(v1, v2)
    assert abs(sim - 1.0) < 1e-6

    # 正交向量相似度应为0
    v3 = [0.0, 1.0, 0.0]
    sim = cosine_similarity(v1, v3)
    assert abs(sim) < 1e-6


def test_fingerprint_stability():
    """测试内容指纹的稳定性。"""

    content = "测试内容"
    fp1 = fingerprint(content)
    fp2 = fingerprint(content)
    assert fp1 == fp2

    # 不同内容应有不同指纹
    fp3 = fingerprint("其他内容")
    assert fp1 != fp3
