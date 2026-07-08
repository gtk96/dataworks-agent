"""DWD SQL generator — incremental/full refresh from structured metadata."""

from __future__ import annotations

from dataworks_agent.modeling.dwd.schemas import FieldMappingInfo, StructuredMetadata


class DwdSQLGenerator:
    """Generate SQL scripts from structured metadata."""

    def generate(
        self,
        metadata: StructuredMetadata,
        *,
        full_refresh_insert_overwrite: bool = False,
    ) -> str:
        if metadata.update_mode == "full":
            return self._generate_full_mode(
                metadata,
                wrap_insert_overwrite=full_refresh_insert_overwrite,
            )
        return self._generate_incremental_mode(metadata)

    def _build_select_expr(self, mapping: FieldMappingInfo) -> str:
        expr = mapping.transform_sql or f"{mapping.source_alias}.{mapping.source_field_name}"

        if mapping.apply_coalesce and mapping.field_category not in ("amount", "quantity"):
            expr = f"COALESCE({expr}, '-')"

        return f"{expr} AS {mapping.target_field_name}"

    def _build_select_clause(self, metadata: StructuredMetadata) -> str:
        expressions = [self._build_select_expr(m) for m in metadata.field_mappings]
        return "SELECT\n    " + ",\n    ".join(expressions)

    def _build_from_clause(self, metadata: StructuredMetadata) -> str:
        mt = metadata.master_table
        return f"FROM {mt.table_name} {mt.alias}"

    def _build_join_clauses(self, metadata: StructuredMetadata) -> str:
        if not metadata.joins:
            return ""
        parts = [
            f"{j.join_type} JOIN {j.right_table_name} {j.right_alias} ON {j.on_condition}"
            for j in metadata.joins
        ]
        return "\n".join(parts)

    def _build_where_clause(self, metadata: StructuredMetadata) -> str:
        if not metadata.partition_fields:
            return ""
        conditions = [
            f"{pf} = '{value}'" for pf, value in self._current_partition_vars(metadata).items()
        ]
        return "WHERE " + " AND ".join(conditions)

    def _generate_full_mode(
        self,
        metadata: StructuredMetadata,
        *,
        wrap_insert_overwrite: bool = False,
    ) -> str:
        parts = [self._build_select_clause(metadata), self._build_from_clause(metadata)]
        join_clause = self._build_join_clauses(metadata)
        if join_clause:
            parts.append(join_clause)
        where_clause = self._build_where_clause(metadata)
        if where_clause:
            parts.append(where_clause)
        select_sql = "\n".join(parts)
        if not wrap_insert_overwrite:
            return select_sql
        cur_vars = self._current_partition_vars(metadata)
        partition_assigns = ", ".join(f"{pf} = '{val}'" for pf, val in cur_vars.items())
        return (
            f"INSERT OVERWRITE TABLE {metadata.target_table_name} "
            f"PARTITION ({partition_assigns})\n{select_sql};"
        )

    def _current_partition_vars(self, metadata: StructuredMetadata) -> dict[str, str]:
        pf_list = metadata.partition_fields if metadata.partition_fields else ["dt"]
        mode = metadata.update_mode
        mapping: dict[str, str] = {}
        for pf in pf_list:
            if pf == "dt":
                mapping[pf] = "${gmtdate}" if mode == "hourly" else "${bizdate}"
            elif pf == "ht":
                mapping[pf] = "${hour_last1h}"
            else:
                mapping[pf] = "${bizdate}"
        return mapping

    def _prev_partition_vars(self, metadata: StructuredMetadata) -> dict[str, str]:
        pf_list = metadata.partition_fields if metadata.partition_fields else ["dt"]
        mode = metadata.update_mode
        mapping: dict[str, str] = {}
        for pf in pf_list:
            if pf == "dt":
                mapping[pf] = "${gmtdate_last1h}" if mode == "hourly" else "${pre_bizdate}"
            elif pf == "ht":
                mapping[pf] = "${hour_last2h}"
            else:
                mapping[pf] = "${pre_bizdate}"
        return mapping

    def _generate_incremental_mode(self, metadata: StructuredMetadata) -> str:
        target = metadata.target_table_name
        cur_vars = self._current_partition_vars(metadata)
        prev_vars = self._prev_partition_vars(metadata)
        pk_fields = metadata.logical_primary_keys

        if not pk_fields:
            raise ValueError("logical_primary_keys must not be empty in incremental mode")

        target_field_names = {m.target_field_name for m in metadata.field_mappings}
        for pk in pk_fields:
            if pk not in target_field_names:
                raise ValueError(
                    f"Logical primary key '{pk}' does not match any target field name. "
                    f"Available target fields: {sorted(target_field_names)}"
                )

        partition_assigns = ", ".join(f"{pf} = '{val}'" for pf, val in cur_vars.items())
        insert_line = f"INSERT OVERWRITE TABLE {target} PARTITION ({partition_assigns})"

        new_select_exprs: list[str] = []
        for mapping in metadata.field_mappings:
            expr = mapping.transform_sql or f"{mapping.source_alias}.{mapping.source_field_name}"
            new_select_exprs.append(f"{expr} AS {mapping.target_field_name}")

        new_select = "SELECT\n    " + ",\n    ".join(new_select_exprs)
        new_from = f"FROM {metadata.master_table.table_name} {metadata.master_table.alias}"

        new_join = ""
        if metadata.joins:
            join_parts = [
                f"{j.join_type} JOIN {j.right_table_name} {j.right_alias}\nON {j.on_condition}"
                for j in metadata.joins
            ]
            new_join = "\n".join(join_parts)

        new_where_conds = [
            f"{metadata.master_table.alias}.{pf} = '{val}'" for pf, val in cur_vars.items()
        ]
        new_where = "WHERE " + " AND ".join(new_where_conds)

        part1_parts = [new_select, new_from]
        if new_join:
            part1_parts.append(new_join)
        part1_parts.append(new_where)
        part1 = "\n".join(part1_parts)

        carry_select_exprs = [f"t1.{m.target_field_name}" for m in metadata.field_mappings]
        carry_select = "SELECT\n    " + ",\n    ".join(carry_select_exprs)
        carry_from = f"FROM {target} t1"

        mt = metadata.master_table
        anti_join_on_parts: list[str] = []
        for pk in pk_fields:
            source_field = pk
            for mapping in metadata.field_mappings:
                if mapping.target_field_name == pk:
                    source_field = mapping.source_field_name
                    break
            anti_join_on_parts.append(f"t1.{pk} = t2.{source_field}")
        for pf, val in cur_vars.items():
            anti_join_on_parts.append(f"t2.{pf} = '{val}'")

        anti_join = f"LEFT ANTI JOIN {mt.table_name} t2\nON {' AND '.join(anti_join_on_parts)}"

        carry_where_conds = [f"t1.{pf} = '{val}'" for pf, val in prev_vars.items()]
        carry_where = "WHERE " + " AND ".join(carry_where_conds)
        part2 = f"{carry_select}\n{carry_from}\n{anti_join}\n{carry_where}"

        main_sql = f"{insert_line}\n{part1}\nUNION ALL\n{part2};"

        # ALTER TABLE for ODS table (pre-create next day's partition)
        # The ODS table is the master table
        mode = metadata.update_mode
        if mode == "hourly":
            # For hourly: pre-create next day's partition with last hour (23)
            # Using gmtdate_next1d for next day's date, hour=23 for last hour
            alter_sql = (
                f"ALTER TABLE {metadata.master_table.table_name} "
                f"ADD IF NOT EXISTS PARTITION "
                f"(dt = '${{gmtdate_next1d}}', ht = '23');"
            )
        else:
            # For daily: pre-create next day's partition
            alter_sql = (
                f"ALTER TABLE {metadata.master_table.table_name} "
                f"ADD IF NOT EXISTS PARTITION (dt = '${{gmtdate_next1d}}');"
            )

        return f"{main_sql}\n\n{alter_sql}"
