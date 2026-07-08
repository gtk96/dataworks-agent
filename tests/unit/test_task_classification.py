"""Task classification tests."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import sqlite

from dataworks_agent.db.models import ModelingTaskModel
from dataworks_agent.services.task_classification import (
    NODE_TYPE_DI,
    NODE_TYPE_HOLO,
    NODE_TYPE_ODPS,
    _classify_status,
    infer_node_type,
    infer_node_type_sql,
    pipeline_node_type,
)


class TestTaskClassification:
    def test_infer_explicit_node_type(self) -> None:
        task = ModelingTaskModel(task_id="x1", node_type=NODE_TYPE_DI, target_layer="ODS")
        assert infer_node_type(task) == NODE_TYPE_DI

    def test_infer_holo_from_task_prefix(self) -> None:
        task = ModelingTaskModel(task_id="holo_abc", node_type="", target_layer="ODS")
        assert infer_node_type(task) == NODE_TYPE_HOLO

    def test_infer_odps_from_task_prefix(self) -> None:
        task = ModelingTaskModel(task_id="task_abc", node_type="", target_layer="DWD")
        assert infer_node_type(task) == NODE_TYPE_ODPS

    def test_pipeline_type_mapping(self) -> None:
        assert pipeline_node_type("ods_oss") == NODE_TYPE_ODPS
        assert pipeline_node_type("ods_realtime") == NODE_TYPE_DI


class TestClassifyStatus:
    """v11：抽 _classify_status 公共逻辑，避免 SQL GROUP BY 与 legacy 路径重复维护。"""

    def test_terminal_states(self) -> None:
        assert _classify_status("completed") == "completed"
        assert _classify_status("success") == "completed"
        assert _classify_status("failed") == "failed"
        assert _classify_status("partial") == "failed"

    def test_in_flight_states(self) -> None:
        # 状态机中间态都归到 running
        for s in (
            "running",
            "ddl_gen",
            "table_cre",
            "root_check",
            "dml_write",
            "sched_cfg",
            "testing",
            "claimed",
        ):
            assert _classify_status(s) == "running", f"{s} 应归 running"

    def test_queued_states(self) -> None:
        assert _classify_status("pending") == "pending"
        assert _classify_status("queued") == "pending"

    def test_unknown_returns_none(self) -> None:
        assert _classify_status("") is None
        assert _classify_status("weird_state") is None
        assert _classify_status(None) is None  # type: ignore[arg-type]

    def test_case_insensitive(self) -> None:
        assert _classify_status("COMPLETED") == "completed"
        assert _classify_status("Running") == "running"


class TestInferNodeTypeSql:
    """v15：SQL 端 infer_node_type_sql 与 Python 端 infer_node_type 行为等价。"""

    def _sql_label(self, task_id: str, node_type: str = "", target_layer: str = "ODS") -> str:
        """构造单行 SELECT，渲染出 SQL 字符串便于肉眼检查关键字。"""
        # 直接看 infer_node_type_sql() 编译输出包含关键关键字即可
        sql = str(
            select(ModelingTaskModel.task_id, infer_node_type_sql().label("n")).compile(
                dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        return sql

    def test_sql_contains_coalesce_and_case(self) -> None:
        """SQL 必须包含 coalesce + 三个 case when（显式/前缀/layer）。"""
        sql = self._sql_label("task_x")
        assert "coalesce" in sql.lower()
        # 三个 CASE WHEN（每个含 'when'）
        assert sql.lower().count("when") >= 3
        # 关键关键字
        assert "holo_%" in sql
        assert "di_%" in sql
        assert "odps-sql" in sql
        assert "DWD" in sql and "DWS" in sql

    def test_sql_with_node_type_filter_renders(self) -> None:
        """node_type 过滤时的 WHERE 子句应包含 CASE WHEN（行为级）。"""
        sql = (
            select(ModelingTaskModel.task_id)
            .where(infer_node_type_sql() == NODE_TYPE_HOLO)
            .compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True})
        )
        compiled = str(sql).lower()
        assert "where" in compiled
        assert "case" in compiled
        assert "holo" in compiled

    def test_sql_uses_or_for_imp_task_prefixes(self) -> None:
        """imp_/task_ 前缀必须用 OR 联合（护栏：防止 SQLAlchemy 退化把 or_ 编译成 AND）。

        R17 自审确认 v15 写法正确后固化此断言：未来 SQLAlchemy 版本升级、
        or_ 在 case.when 条件语义若变，此测试会先红。
        """
        sql = str(
            select(ModelingTaskModel.task_id, infer_node_type_sql().label("n")).compile(
                dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        lower = sql.lower()
        # 必须含 OR（imp_ 与 task_ 前缀条件用 OR 连接）
        assert "or" in lower, f"应含 OR（imp_/task_ 前缀用 OR），实际 SQL：{sql}"
        # 断言 'imp_%' 和 'task_%' 之间必须用 'OR' 而非 'AND'。
        # 实际 SQL 是 "LIKE 'imp_%' OR modeling_tasks.task_id LIKE 'task_%'"，
        # LIKE 与 'imp_%' 中间夹 modeling_tasks.task_id 列前缀。
        import re

        match = re.search(r"like\s+'imp_%'\s+(or|and)\s+\S+\.\S+\s+like\s+'task_%'", lower)
        assert match is not None, f"imp_/task_ LIKE 模式未紧邻出现：{sql}"
        assert match.group(1) == "or", f"imp_/task_ 必须用 OR，实际用 {match.group(1)}"
