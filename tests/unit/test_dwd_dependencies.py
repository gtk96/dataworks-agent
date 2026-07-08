"""Test find_ods_sources — 1:N DWD dependency extraction."""

from dataworks_agent.modeling.dwd.dependencies import find_ods_sources


class TestFindOdssSources:
    """Extract all ODS tables referenced in DML via FROM/JOIN."""

    def test_single_from(self):
        dml = "INSERT OVERWRITE TABLE dwd_x SELECT * FROM dataworks.ods_a WHERE ..."
        assert find_ods_sources(dml) == ["ods_a"]

    def test_multiple_joins(self):
        dml = """
        INSERT OVERWRITE TABLE dwd_order SELECT
          a.id, b.name, c.amount
        FROM dataworks.ods_order a
        JOIN dataworks.ods_user b ON a.uid = b.id
        JOIN dataworks.ods_pay c ON a.id = c.order_id
        """
        sources = find_ods_sources(dml)
        assert "ods_order" in sources
        assert "ods_user" in sources
        assert "ods_pay" in sources
        assert len(sources) == 3

    def test_skip_comments(self):
        dml = """
        -- This joins dataworks.ods_hidden
        INSERT INTO t SELECT * FROM dataworks.ods_visible
        """
        assert find_ods_sources(dml) == ["ods_visible"]

    def test_skip_inline_comment(self):
        dml = "SELECT * FROM dataworks.ods_a -- dataworks.ods_b\nWHERE id > 0"
        assert find_ods_sources(dml) == ["ods_a"]

    def test_no_datasource_prefix(self):
        dml = "SELECT * FROM ods_plain WHERE 1"
        assert find_ods_sources(dml) == []

    def test_case_insensitive(self):
        dml = "select * from DATAWORKS.ODS_UPPER join DataWorks.ods_mixed on 1=1"
        sources = find_ods_sources(dml)
        assert "ODS_UPPER" in sources
        assert "ods_mixed" in sources

    def test_dedup(self):
        dml = "SELECT * FROM dataworks.ods_a JOIN dataworks.ods_a ON 1=1"
        assert find_ods_sources(dml) == ["ods_a"]
