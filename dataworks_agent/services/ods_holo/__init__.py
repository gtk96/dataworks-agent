"""ODS Holo SQL — production DML generation."""

from dataworks_agent.services.ods_holo.dml_generator import (
    build_holo_ods_dml,
    extract_dml_for_table,
)

__all__ = ["build_holo_ods_dml", "extract_dml_for_table"]
