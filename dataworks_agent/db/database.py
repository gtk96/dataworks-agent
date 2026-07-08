"""SQLite 数据库连接 — WAL 模式 + StaticPool + busy_timeout。"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from dataworks_agent.config import settings

DATABASE_URL = f"sqlite:///{settings.db_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 10,
    },
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def _ensure_columns(eng=engine) -> None:
    """对既有表补齐 ORM 新增列（无 Alembic 的轻量自愈迁移）。

    `create_all` 只建新表、不改既有表结构。历史库（如 data/dw_modeling.db）缺
    Task 7 新增的 `actor_team`/`actor_org_code`/`span_id`/`seq` 等列会导致启动即
    崩。此处按 ORM metadata 幂等地对已存在的表 ADD COLUMN 补齐缺失列（新增列均带
    字面默认值，加为可空以避免 NOT NULL 回填失败；索引由 create_all 仅覆盖新表，
    补列不建索引，属可接受的性能取舍）。
    """
    from sqlalchemy import inspect

    insp = inspect(eng)
    existing = set(insp.get_table_names())
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue  # 新表交给 create_all
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                coltype = col.type.compile(dialect=eng.dialect)
                default_sql = ""
                arg = getattr(col.default, "arg", None) if col.default is not None else None
                if arg is not None and not callable(arg):
                    default_sql = f" DEFAULT '{arg}'" if isinstance(arg, str) else f" DEFAULT {arg}"
                conn.exec_driver_sql(
                    f"ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}{default_sql}"
                )


def init_db() -> None:
    """创建所有表并开启 WAL 模式。"""
    import dataworks_agent.db.models  # noqa: F401 — 触发模型注册

    Base.metadata.create_all(bind=engine)
    _ensure_columns(engine)

    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
        conn.exec_driver_sql("PRAGMA busy_timeout=10000")
        conn.commit()


def get_session():
    """FastAPI 依赖注入 — 每次请求一个短事务 session。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
