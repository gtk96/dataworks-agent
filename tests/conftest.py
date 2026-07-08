"""通用 fixtures — cleanup_tracker、test_suffix、SQLite 初始化、语义口径种子。"""

from __future__ import annotations

import os

# 须在 import dataworks_agent 前注入，满足 Settings cookie_encryption_key 校验（v10 §6.1）
os.environ.setdefault("COOKIE_ENCRYPTION_KEY", "test-cookie-key-for-ci-min16")

import uuid
from pathlib import Path

import _pytest.pathlib
import pytest


def _safe_make_num(*, root, prefix, mode, keep, lock_timeout, register):
    try:
        return _pytest.pathlib.make_numbered_dir_with_cleanup(
            root=root,
            prefix=prefix,
            mode=mode,
            keep=keep,
            lock_timeout=lock_timeout,
            register=register,
        )
    except PermissionError:
        import tempfile as _tf

        p = Path(_tf.mkdtemp(prefix=f"{prefix}_fallback_"))
        # 展开 8.3 短名，SQLite 无法在短名路径创建 .db
        return p.resolve()


_pytest.pathlib.make_numbered_dir_with_cleanup = _safe_make_num


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    """初始化测试用 SQLite 表结构（ORM create_all）。"""
    from dataworks_agent.db.database import init_db

    init_db()


@pytest.fixture
def test_suffix() -> str:
    """隔离并发测试 / 临时资源后缀。"""
    return f"e2e_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def cleanup_tracker() -> dict:
    """记录测试创建的 DataWorks 资源，teardown 时清理。"""
    resources: dict[str, list[str]] = {"tables": [], "nodes": [], "di_jobs": []}
    yield resources


@pytest.fixture(scope="session", autouse=True)
def _seed_semantic_defs():
    """CI 上 SQLite 是空库；预注册 Agent 测试用的口径 order_count。

    本地 data/dw_modeling.db 可能已有同名行（历史遗留），用 if-not-exists 守护；
    仅当 approved 行不存在时插入，不影响其它测试。
    """
    from dataworks_agent.db.database import SessionLocal
    from dataworks_agent.db.models import SemanticDefModel

    with SessionLocal() as db:
        exists = (
            db.query(SemanticDefModel)
            .filter(
                SemanticDefModel.kind == "metric",
                SemanticDefModel.key == "order_count",
                SemanticDefModel.status == "approved",
            )
            .first()
        )
        if not exists:
            db.add(
                SemanticDefModel(
                    def_id="seed_metric_order_count_v1",
                    kind="metric",
                    key="order_count",
                    body_json=(
                        '{"name":"订单数量","unit":"count",'
                        '"sql":"SELECT COUNT(*) FROM ods_ord_order_hour"}'
                    ),
                    version=1,
                    source="manual",
                    status="approved",
                    created_by="ci_seed",
                )
            )
            db.commit()
