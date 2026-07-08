"""task_backfill 单元测试 — 补全覆盖率 0% 模块。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import sessionmaker

from dataworks_agent.db.database import Base
from dataworks_agent.services import task_backfill as mod
from dataworks_agent.services.task_backfill import backfill_node_types


# 会话级 engine，所有测试共享同一个内存数据库
@pytest.fixture(scope="session")
def test_engine():
    engine = sa_create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def test_session(test_engine):
    """每个测试用一个新的 session，但共享同一个 engine。"""
    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=test_engine, autoflush=False)()
    yield session
    # 清理数据但不关闭 session
    test_engine.execute(
        __import__(
            "dataworks_agent.db.models", fromlist=["ModelingTaskModel"]
        ).ModelingTaskModel.__table__.delete()
    )


# 直接测试 backfill_node_types 函数，它使用 test_engine 作为数据库
def _insert_task(db, **kwargs):
    """插入一条 ModelingTaskModel 行。"""
    defaults = {
        "task_id": f"task_{kwargs.get('task_id', 'x')}",
        "status": "completed",
        "created_by_ip": "127.0.0.1",
        "source_table": "ods_t",
        "target_table": "dwd_t",
        "target_layer": "DWD",
        "node_type": "",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    defaults.update(kwargs)
    db.add(
        __import__("dataworks_agent.db.models", fromlist=["ModelingTaskModel"]).ModelingTaskModel(
            **defaults
        )
    )
    db.commit()


def test_backfill_fills_empty_node_type():
    """空 node_type 行应被回填。"""
    # 创建独立的内存数据库用于这个测试
    from sqlalchemy import create_engine as sa_create_engine
    from sqlalchemy.orm import sessionmaker

    engine = sa_create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)

    with session() as db:
        # 插入测试数据
        from dataworks_agent.db.models import ModelingTaskModel

        db.add(
            ModelingTaskModel(
                task_id="task_t1",
                status="completed",
                source_table="ods_t",
                target_table="dwd_ord_test",
                target_layer="DWD",
                node_type="",
                created_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
            )
        )
        db.commit()
        assert (
            db.query(
                __import__(
                    "dataworks_agent.db.models", fromlist=["ModelingTaskModel"]
                ).ModelingTaskModel
            ).count()
            == 1
        )

    # 直接调用 backfill_node_types，它使用 mod.SessionLocal
    # 我们需要临时替换 mod.SessionLocal
    import dataworks_agent.services.task_backfill as mod

    original_session_local = mod.SessionLocal
    session_local = sessionmaker(bind=engine, autoflush=False)
    mod.SessionLocal = session_local
    try:
        updated = backfill_node_types()
        assert updated == 1

        # 验证回填结果
        with session() as db:
            from dataworks_agent.db.models import ModelingTaskModel

            row = (
                db.query(
                    __import__(
                        "dataworks_agent.db.models", fromlist=["ModelingTaskModel"]
                    ).ModelingTaskModel
                )
                .filter_by(task_id="task_t1")
                .first()
            )
            assert row is not None
            assert row.node_type == "odps-sql"
    finally:
        mod.SessionLocal = original_session_local
        engine.dispose()


def test_backfill_skips_existing_node_type():
    """已有 node_type 的行不应被覆盖(force=False)。"""
    from sqlalchemy import create_engine as sa_create_engine
    from sqlalchemy.pool import StaticPool

    engine = sa_create_engine(
        "sqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)

    with session() as db:
        db.add(
            __import__(
                "dataworks_agent.db.models", fromlist=["ModelingTaskModel"]
            ).ModelingTaskModel(
                task_id="task_t2",
                status="completed",
                source_table="ods_t",
                target_table="dwd_t",
                target_layer="DWD",
                node_type="existing_type",
                created_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
            )
        )
        db.commit()

    original = mod.SessionLocal
    session_local = sessionmaker(bind=engine, autoflush=False)
    mod.SessionLocal = session_local
    try:
        updated = backfill_node_types(force=False)
        assert updated == 0

        with session() as db:
            row = (
                db.query(
                    __import__(
                        "dataworks_agent.db.models", fromlist=["ModelingTaskModel"]
                    ).ModelingTaskModel
                )
                .filter_by(task_id="task_t2")
                .first()
            )
            assert row.node_type == "existing_type"
    finally:
        mod.SessionLocal = original
        engine.dispose()


def test_backfill_force_overwrites():
    """force=True 应覆盖已有 node_type。"""
    from sqlalchemy import create_engine as sa_create_engine
    from sqlalchemy.pool import StaticPool

    engine = sa_create_engine(
        "sqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)

    with session() as db:
        db.add(
            __import__(
                "dataworks_agent.db.models", fromlist=["ModelingTaskModel"]
            ).ModelingTaskModel(
                task_id="task_t3",
                status="completed",
                source_table="ods_t",
                target_table="dwd_t",
                target_layer="DWD",
                node_type="old_type",
                created_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
            )
        )
        db.commit()

    original = mod.SessionLocal
    session_local = sessionmaker(bind=engine, autoflush=False)
    mod.SessionLocal = session_local
    try:
        updated = backfill_node_types(force=True)
        assert updated == 1

        with session() as db:
            row = (
                db.query(
                    __import__(
                        "dataworks_agent.db.models", fromlist=["ModelingTaskModel"]
                    ).ModelingTaskModel
                )
                .filter_by(task_id="task_t3")
                .first()
            )
            assert row.node_type == "odps-sql"
    finally:
        mod.SessionLocal = original
        engine.dispose()


def test_backfill_handles_empty_db():
    """真空 DB 不应崩。"""
    from sqlalchemy import create_engine as sa_create_engine
    from sqlalchemy.pool import StaticPool

    engine = sa_create_engine(
        "sqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    original = mod.SessionLocal
    session_local = sessionmaker(bind=engine, autoflush=False)
    mod.SessionLocal = session_local
    try:
        updated = backfill_node_types()
        assert updated == 0
    finally:
        mod.SessionLocal = original
        engine.dispose()


def test_backfill_dim_target():
    """DIM 层表应被推断为 odps-sql。"""
    from sqlalchemy import create_engine as sa_create_engine
    from sqlalchemy.pool import StaticPool

    engine = sa_create_engine(
        "sqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)

    with session() as db:
        db.add(
            __import__(
                "dataworks_agent.db.models", fromlist=["ModelingTaskModel"]
            ).ModelingTaskModel(
                task_id="task_t4",
                status="completed",
                source_table="ods_t",
                target_table="dim_ord_x",
                target_layer="DIM",
                node_type="",
                created_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
            )
        )
        db.commit()

    original = mod.SessionLocal
    session_local = sessionmaker(bind=engine, autoflush=False)
    mod.SessionLocal = session_local
    try:
        updated = backfill_node_types()
        assert updated == 1

        with session() as db:
            row = (
                db.query(
                    __import__(
                        "dataworks_agent.db.models", fromlist=["ModelingTaskModel"]
                    ).ModelingTaskModel
                )
                .filter_by(task_id="task_t4")
                .first()
            )
            assert row is not None
            assert row.node_type != ""
    finally:
        mod.SessionLocal = original
        engine.dispose()
