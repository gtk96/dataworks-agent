"""任务 Memory 服务单元测试 — Loop Engineering Memory 持久化。"""

import uuid

import pytest

from dataworks_agent.task_engine.task_memory import (
    ArtifactRef,
    Blocker,
    Decision,
    NextStep,
    StepRecord,
    TaskMemory,
    TaskMemoryService,
)


@pytest.fixture
def service():
    """创建 Memory 服务实例。"""
    return TaskMemoryService()


def _unique_id() -> str:
    """生成唯一 ID。"""
    return f"task_test_{uuid.uuid4().hex[:8]}"


def test_get_or_create(service):
    """获取或创建任务 Memory。"""
    task_id = _unique_id()
    # 创建新 Memory
    memory = service.get_or_create(task_id, session_id="session_001")
    assert memory.task_id == task_id
    assert memory.session_id == "session_001"

    # 获取已存在的 Memory
    memory2 = service.get_or_create(task_id)
    assert memory2.task_id == task_id


def test_append_step(service):
    """追加步骤记录。"""
    task_id = _unique_id()
    service.get_or_create(task_id)

    step = StepRecord(
        step_name="ddl_gen",
        status="completed",
        result={"table_name": "dwd_test_day"},
    )
    service.append_step(task_id, step)

    memory = service.get(task_id)
    assert memory is not None
    assert len(memory.completed_steps) == 1
    assert memory.completed_steps[0].step_name == "ddl_gen"


def test_append_decision(service):
    """追加决策记录。"""
    task_id = _unique_id()
    service.get_or_create(task_id)

    decision = Decision(
        decision="使用 MaxCompute 建表",
        reason="AK/SK 权限覆盖",
        alternatives=["使用 BFF 建表"],
    )
    service.append_decision(task_id, decision)

    memory = service.get(task_id)
    assert memory is not None
    assert len(memory.decisions) == 1
    assert memory.decisions[0].decision == "使用 MaxCompute 建表"


def test_append_artifact(service):
    """追加产物引用。"""
    task_id = _unique_id()
    service.get_or_create(task_id)

    artifact = ArtifactRef(
        artifact_type="node",
        artifact_id="node_12345",
        description="DWD 节点",
        location="业务流程/100_订单信息/MaxCompute/数据开发/02_DWD/",
    )
    service.append_artifact(task_id, artifact)

    memory = service.get(task_id)
    assert memory is not None
    assert len(memory.artifacts) == 1
    assert memory.artifacts[0].artifact_id == "node_12345"


def test_set_next_steps(service):
    """设置下一步建议。"""
    task_id = _unique_id()
    service.get_or_create(task_id)

    next_steps = [
        NextStep(
            step_type="dml_push",
            description="推送 DML",
            priority=1,
        ),
        NextStep(
            step_type="verification",
            description="运行验收检查",
            priority=99,
        ),
    ]
    service.set_next_steps(task_id, next_steps)

    memory = service.get(task_id)
    assert memory is not None
    assert len(memory.next_steps) == 2
    assert memory.next_steps[0].step_type == "dml_push"


def test_append_blocker(service):
    """追加阻塞项。"""
    task_id = _unique_id()
    service.get_or_create(task_id)

    blocker = Blocker(
        blocker_type="permission",
        description="AK/SK 无权限",
    )
    service.append_blocker(task_id, blocker)

    memory = service.get(task_id)
    assert memory is not None
    assert len(memory.blockers) == 1

    # 清除阻塞项
    service.clear_blockers(task_id)
    memory = service.get(task_id)
    assert len(memory.blockers) == 0


def test_set_verification(service):
    """设置验收状态。"""
    task_id = _unique_id()
    service.get_or_create(task_id)

    service.set_verification(
        task_id,
        "passed",
        {"passed_count": 4, "failed_count": 0},
    )

    memory = service.get(task_id)
    assert memory is not None
    assert memory.verification_status == "passed"
    assert memory.verification_result["passed_count"] == 4


def test_generate_next_steps_ods(service):
    """生成 ODS 任务的下一步建议。"""
    task_id = _unique_id()
    service.get_or_create(task_id)

    next_steps = service.generate_next_steps(
        task_id,
        "ODS",
        {"table_name": "ods_ord_order_hour"},
    )

    assert len(next_steps) >= 2
    step_types = [s.step_type for s in next_steps]
    assert "dml_push" in step_types
    assert "verification" in step_types


def test_generate_next_steps_dwd(service):
    """生成 DWD 任务的下一步建议。"""
    task_id = _unique_id()
    service.get_or_create(task_id)

    next_steps = service.generate_next_steps(
        task_id,
        "DWD",
        {"table_name": "dwd_ord_order_detail_day"},
    )

    assert len(next_steps) >= 3
    step_types = [s.step_type for s in next_steps]
    assert "dml_push" in step_types
    assert "dependency_config" in step_types
    assert "verification" in step_types


def test_generate_next_steps_dim(service):
    """生成 DIM 任务的下一步建议。"""
    task_id = _unique_id()
    service.get_or_create(task_id)

    next_steps = service.generate_next_steps(
        task_id,
        "DIM",
        {"table_name": "dim_ord_product_all"},
    )

    assert len(next_steps) >= 3
    step_types = [s.step_type for s in next_steps]
    assert "dml_push" in step_types
    assert "dependency_config" in step_types
    assert "verification" in step_types


def test_task_memory_to_dict():
    """TaskMemory 转字典。"""
    memory = TaskMemory(
        task_id="task_001",
        session_id="session_001",
        completed_steps=[
            StepRecord(step_name="step1", status="completed"),
        ],
        current_step="step2",
        decisions=[
            Decision(decision="选择方案A", reason="性能更好"),
        ],
        artifacts=[
            ArtifactRef(artifact_type="node", artifact_id="node_001"),
        ],
        next_steps=[
            NextStep(step_type="verification", description="运行验收"),
        ],
        blockers=[
            Blocker(blocker_type="permission", description="无权限"),
        ],
        verification_status="passed",
        verification_result={"passed_count": 4},
    )

    d = memory.to_dict()
    assert d["task_id"] == "task_001"
    assert len(d["completed_steps"]) == 1
    assert len(d["decisions"]) == 1
    assert len(d["artifacts"]) == 1
    assert len(d["next_steps"]) == 1
    assert len(d["blockers"]) == 1
    assert d["verification_status"] == "passed"
