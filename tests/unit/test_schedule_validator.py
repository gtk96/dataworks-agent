"""0 点边界调度参数校验单元测试。"""

from dataworks_agent.modeling.schedule_config import ScheduleValidator


def test_daily_params():
    preview = ScheduleValidator.preview_params("Daily", biz_hour=7)
    assert "正常调度" in preview.scenarios
    assert "0点边界" in preview.scenarios
    assert "月底边界" in preview.scenarios
    assert "跨年边界" in preview.scenarios

    # 正常调度应包含 bizdate 和 biz_date
    normal = preview.scenarios["正常调度"]
    assert "bizdate" in normal
    assert "biz_date" in normal


def test_hourly_params():
    preview = ScheduleValidator.preview_params("NotDaily")
    assert "正常调度" in preview.scenarios

    normal = preview.scenarios["正常调度"]
    assert "gmtdate" in normal
    assert "hour_last1h" in normal


def test_validate_missing_params():
    from dataworks_agent.schemas import ScheduleParameter

    params = [ScheduleParameter(name="bizdate", value="$[yyyymmdd-1]")]
    errors = ScheduleValidator.validate(params)
    assert len(errors) == 1
    assert "biz_date" in errors[0]


def test_validate_complete_params():
    from dataworks_agent.schemas import ScheduleParameter

    params = [
        ScheduleParameter(name="bizdate", value="$[yyyymmdd-1]"),
        ScheduleParameter(name="biz_date", value="$[yyyy-mm-dd-1]"),
    ]
    errors = ScheduleValidator.validate(params)
    assert len(errors) == 0
