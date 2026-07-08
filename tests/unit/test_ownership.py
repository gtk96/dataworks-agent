"""OwnershipTracker ? ?????????"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dataworks_agent.db.database import Base
from dataworks_agent.modeling.ownership import OwnershipTracker
from dataworks_agent.schemas import OwnershipRecord


@pytest.fixture
def tracker():
    """???? SQLite ?? Windows ???/SQLite I/O ???"""
    engine = sa_create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False)
    with patch("dataworks_agent.db.database.SessionLocal", test_session):
        t = OwnershipTracker()
        yield t


@pytest.mark.asyncio
async def test_record_table_creation_writes_record(tracker: OwnershipTracker):
    await tracker.record_table_creation("dwd_test", "127.0.0.1")
    records = await tracker.get_table_owners("dwd_test")
    assert len(records) == 1
    assert records[0].table_name == "dwd_test"
    assert records[0].change_type == "create"
    assert records[0].created_by_ip == "127.0.0.1"
    assert records[0].created_at


@pytest.mark.asyncio
async def test_record_table_creation_multiple_times_appends(tracker: OwnershipTracker):
    await tracker.record_table_creation("dwd_test", "127.0.0.1")
    await tracker.record_table_creation("dwd_test", "10.0.0.1")
    records = await tracker.get_table_owners("dwd_test")
    assert len(records) == 2
    ips = {r.created_by_ip for r in records}
    assert ips == {"127.0.0.1", "10.0.0.1"}


@pytest.mark.asyncio
async def test_record_field_change_writes_with_field(tracker: OwnershipTracker):
    await tracker.record_field_change("dwd_test", "order_amt", "alter", "10.0.0.1")
    records = await tracker.get_table_owners("dwd_test")
    assert len(records) == 1
    assert records[0].field_name == "order_amt"
    assert records[0].change_type == "alter"
    assert records[0].last_modified_by_ip == "10.0.0.1"


@pytest.mark.asyncio
async def test_get_table_owners_filters_by_table(tracker: OwnershipTracker):
    await tracker.record_table_creation("dwd_a", "127.0.0.1")
    await tracker.record_table_creation("dwd_b", "127.0.0.1")
    await tracker.record_field_change("dwd_b", "col1", "alter", "10.0.0.1")
    a = await tracker.get_table_owners("dwd_a")
    b = await tracker.get_table_owners("dwd_b")
    assert {r.table_name for r in a} == {"dwd_a"}
    assert {r.table_name for r in b} == {"dwd_b"}
    assert len(b) == 2


@pytest.mark.asyncio
async def test_get_table_owners_empty_for_unknown(tracker: OwnershipTracker):
    records = await tracker.get_table_owners("nonexistent")
    assert records == []


@pytest.mark.asyncio
async def test_record_returns_ownership_record_schema(tracker: OwnershipTracker):
    await tracker.record_table_creation("dwd_test", "127.0.0.1")
    record = (await tracker.get_table_owners("dwd_test"))[0]
    assert isinstance(record, OwnershipRecord)
    assert hasattr(record, "table_name")
    assert hasattr(record, "field_name")
    assert hasattr(record, "created_by_ip")
    assert hasattr(record, "last_modified_by_ip")
    assert hasattr(record, "business_owner")
    assert hasattr(record, "change_type")
    assert hasattr(record, "created_at")
