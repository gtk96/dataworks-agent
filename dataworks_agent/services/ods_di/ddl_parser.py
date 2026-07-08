"""DDL parser using sqlglot to extract table structure from CREATE TABLE statements.

Migrated from dwd-visual-designer with the following capabilities:
- Parse CREATE TABLE DDL using sqlglot
- Extract table name, column names, column types, and column comments
- Auto-detect dialect: tries hive → mysql → postgres → generic
- Raise DDLParseError for invalid DDL input
- Support MaxCompute LIFECYCLE clause stripping
- Support Hive PARTITIONED BY clause extraction

Validates: Requirements 16.1, 16.2, 16.3
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

import sqlglot
from sqlglot import exp


@dataclass
class FieldInfo:
    name: str
    type: str
    comment: str | None = None


@dataclass
class TableStructure:
    table_name: str
    fields: list[FieldInfo]
    table_comment: str | None = None


class DDLParseError(Exception):
    """Raised when a DDL statement cannot be parsed."""


class DDLParser:
    """Parse CREATE TABLE DDL statements and extract table structure.

    Supports MaxCompute, Hive, MySQL, and PostgreSQL dialects via
    automatic detection (tries hive → mysql → postgres → generic).
    """

    def parse(self, ddl_statement: str) -> TableStructure:
        """Parse a CREATE TABLE DDL and return a TableStructure.

        Supports:
        - Standard SQL CREATE TABLE
        - Hive-style DDL with COMMENT after column definition
        - Partitioned tables (PARTITIONED BY clause)
        - Various column types (STRING, BIGINT, DECIMAL, etc.)
        - MaxCompute LIFECYCLE clause

        Args:
            ddl_statement: A CREATE TABLE DDL string.

        Returns:
            TableStructure with table name and field list.

        Raises:
            DDLParseError: If the DDL is invalid or not a CREATE TABLE.
        """
        ddl_statement = self._normalize_statement(ddl_statement)
        if not ddl_statement:
            raise DDLParseError("DDL statement is empty")

        # Try multiple dialects for broader compatibility.
        # If parsing fails, retry once with quoted CREATE TABLE identifier
        # to support reserved keywords as table names (for example: `on`).
        parsed, last_error = self._parse_with_fallback(ddl_statement)

        # If sqlglot cannot produce a CREATE node (e.g. a column name is a SQL
        # reserved word like ``if``/``on`` and sqlglot falls back to a Command),
        # use a tokenizer-independent regex extractor instead of failing.
        if parsed is None or not isinstance(parsed, exp.Create):
            structure = self._regex_fallback_parse(ddl_statement)
            if structure is not None:
                return structure
            if parsed is None:
                msg = f"Failed to parse DDL: {last_error}" if last_error else "Failed to parse DDL"
                raise DDLParseError(msg)
            raise DDLParseError(f"Expected a CREATE TABLE statement, got {type(parsed).__name__}")

        # Extract table name
        table_expr = parsed.find(exp.Table)
        if table_expr is None:
            raise DDLParseError("Could not extract table name from DDL")

        table_name = table_expr.name
        # Include database/schema prefix if present
        if table_expr.db:
            table_name = f"{table_expr.db}.{table_name}"

        # Extract columns from the schema (column definitions)
        fields: list[FieldInfo] = []
        schema = parsed.find(exp.Schema)
        if schema is None:
            raise DDLParseError("No column definitions found in DDL")

        for col_def in schema.find_all(exp.ColumnDef):
            col_name = col_def.name
            col_type = self._extract_column_type(col_def)
            col_comment = self._extract_column_comment(col_def)
            fields.append(FieldInfo(name=col_name, type=col_type, comment=col_comment))

        # Also extract partition columns if present (Hive PARTITIONED BY)
        partition_fields = self._extract_partition_columns(ddl_statement, parsed)
        fields.extend(partition_fields)

        if not fields:
            raise DDLParseError("No columns found in DDL")

        table_comment = self._extract_table_comment(ddl_statement, parsed)
        return TableStructure(table_name=table_name, fields=fields, table_comment=table_comment)

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize_statement(self, ddl_statement: str) -> str:
        """Normalize dialect-specific suffixes that sqlglot cannot parse.

        MaxCompute supports ``LIFECYCLE <n>`` in CREATE TABLE, while sqlglot
        may parse it as a standalone command and lose the CREATE node.  We
        remove this clause before parsing so the table schema can still be
        extracted.
        """
        cleaned = ddl_statement.strip()
        if not cleaned:
            return cleaned

        # Strip MaxCompute LIFECYCLE clause
        cleaned = re.sub(
            r"\bLIFECYCLE\s+\d+\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\n\s*\n+", "\n", cleaned)
        cleaned = re.sub(r"\s+;", ";", cleaned)
        return cleaned

    # ------------------------------------------------------------------
    # Multi-dialect parsing with fallback
    # ------------------------------------------------------------------

    def _parse_with_fallback(
        self, ddl_statement: str
    ) -> tuple[exp.Expression | None, Exception | None]:
        parsed, last_error = self._parse_multi_dialect(ddl_statement)
        if parsed is not None:
            return parsed, last_error

        # Retry with quoted identifier for reserved-keyword table names
        quoted = self._quote_create_table_identifier(ddl_statement)
        if quoted != ddl_statement:
            parsed, quoted_error = self._parse_multi_dialect(quoted)
            if parsed is not None:
                return parsed, quoted_error
            last_error = quoted_error or last_error

        return None, last_error

    def _parse_multi_dialect(
        self, ddl_statement: str
    ) -> tuple[exp.Expression | None, Exception | None]:
        """Try parsing with hive → mysql → postgres → generic dialects."""
        parsed = None
        last_error: Exception | None = None
        for dialect in ("hive", "mysql", "postgres", None):
            try:
                expressions = sqlglot.parse(
                    ddl_statement,
                    read=dialect,
                    error_level=sqlglot.ErrorLevel.RAISE,
                )
                if expressions and expressions[0] is not None:
                    parsed = expressions[0]
                    break
            except Exception as e:
                last_error = e
                continue
        return parsed, last_error

    def _quote_create_table_identifier(self, ddl_statement: str) -> str:
        """Quote CREATE TABLE identifier when it is bare/unquoted."""
        match = re.match(
            r"^(\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)([^\s(]+)",
            ddl_statement,
            flags=re.IGNORECASE,
        )
        if not match:
            return ddl_statement

        raw_name = match.group(2)
        if raw_name.startswith(("`", '"', "[")):
            return ddl_statement

        def _quote_part(part: str) -> str:
            if part.startswith(("`", '"', "[")):
                return part
            return f"`{part}`"

        quoted_name = ".".join(_quote_part(p) for p in raw_name.split("."))
        return ddl_statement[: match.start(2)] + quoted_name + ddl_statement[match.end(2) :]

    # ------------------------------------------------------------------
    # Column extraction helpers
    # ------------------------------------------------------------------

    def _extract_column_type(self, col_def: exp.ColumnDef) -> str:
        """Extract the data type string from a column definition."""
        data_type = col_def.find(exp.DataType)
        if data_type is None:
            return "STRING"
        return data_type.sql(dialect="hive").upper()

    def _extract_column_comment(self, col_def: exp.ColumnDef) -> str | None:
        """Extract COMMENT from a column definition if present."""
        for constraint in col_def.find_all(exp.CommentColumnConstraint):
            comment_val = constraint.find(exp.Literal)
            if comment_val:
                return comment_val.this
        return None

    # ------------------------------------------------------------------
    # Partition column extraction
    # ------------------------------------------------------------------

    def _extract_partition_columns(self, ddl_text: str, parsed: exp.Create) -> list[FieldInfo]:
        """Extract partition columns from PARTITIONED BY clause.

        sqlglot may or may not parse PARTITIONED BY depending on dialect.
        We use a regex fallback to handle Hive-style partition definitions.
        """
        # First try sqlglot's PartitionedByProperty
        for prop in parsed.find_all(exp.PartitionedByProperty):
            partition_fields: list[FieldInfo] = []
            for col_def in prop.find_all(exp.ColumnDef):
                col_name = col_def.name
                col_type = self._extract_column_type(col_def)
                col_comment = self._extract_column_comment(col_def)
                partition_fields.append(
                    FieldInfo(name=col_name, type=col_type, comment=col_comment)
                )
            if partition_fields:
                return partition_fields

        # Regex fallback for PARTITIONED BY (col_name type COMMENT '...')
        pattern = r"PARTITIONED\s+BY\s*\((.*?)\)"
        match = re.search(pattern, ddl_text, re.IGNORECASE | re.DOTALL)
        if not match:
            return []

        partition_block = match.group(1).strip()
        return self._parse_partition_block(partition_block)

    def _parse_partition_block(self, block: str) -> list[FieldInfo]:
        """Parse the content inside PARTITIONED BY (...)."""
        fields: list[FieldInfo] = []
        parts = self._split_columns(block)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            field = self._parse_single_partition_col(part)
            if field:
                fields.append(field)
        return fields

    def _parse_single_partition_col(self, col_text: str) -> FieldInfo | None:
        """Parse a single partition column definition like ``dt STRING COMMENT 'date'``."""
        col_text = col_text.strip().strip("`").strip()
        comment_match = re.search(r"COMMENT\s+['\"](.+?)['\"]", col_text, re.IGNORECASE)
        comment = comment_match.group(1) if comment_match else None

        # Remove COMMENT clause for easier parsing
        clean = re.sub(r"\s*COMMENT\s+['\"].*?['\"]", "", col_text, flags=re.IGNORECASE).strip()

        tokens = clean.split()
        if not tokens:
            return None

        name = tokens[0].strip("`").strip("'").strip('"')
        col_type = tokens[1].upper() if len(tokens) > 1 else "STRING"

        return FieldInfo(name=name, type=col_type, comment=comment)

    # ------------------------------------------------------------------
    # Table-level COMMENT extraction
    # ------------------------------------------------------------------

    def _extract_table_comment(self, ddl_text: str, parsed: exp.Create | None = None) -> str | None:
        """Extract the table-level COMMENT from the DDL.

        Tries sqlglot SchemaCommentProperty first; falls back to regex for
        MaxCompute ``COMMENT 'xxx'`` after the column-block closing paren.
        The regex is anchored after the first balanced ``(...)`` block
        (the column definitions) to avoid matching column-level COMMENT strings.
        """
        if parsed is not None:
            for prop in parsed.find_all(exp.SchemaCommentProperty):
                literal = prop.find(exp.Literal)
                if literal:
                    return literal.this

        # Find the end of the column-definition block (first balanced paren pair)
        name_match = re.match(
            r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[^\s(]+",
            ddl_text,
            flags=re.IGNORECASE,
        )
        start_at = name_match.end() if name_match else 0
        block_end = self._find_paren_block_end(ddl_text, start_at)
        if block_end is None:
            return None

        # Only search for COMMENT after the column block's closing paren
        after_block = ddl_text[block_end:]
        match = re.search(
            r"^\s*COMMENT\s+['\"](.+?)['\"]",
            after_block,
            re.IGNORECASE | re.DOTALL,
        )
        return match.group(1) if match else None

    def _find_paren_block_end(self, text: str, start_at: int) -> int | None:
        """Return the index just past the closing ``)`` of the first balanced paren block."""
        open_idx = text.find("(", start_at)
        if open_idx == -1:
            return None
        depth = 0
        quote: str | None = None
        for i in range(open_idx, len(text)):
            char = text[i]
            if quote is not None:
                if char == quote:
                    quote = None
                continue
            if char in ("'", '"', "`"):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
        return None

    # ------------------------------------------------------------------
    # Regex fallback parser (tokenizer-independent)
    # ------------------------------------------------------------------

    # Leading tokens that indicate a table-level constraint rather than a column.
    _NON_COLUMN_TOKENS: ClassVar[set[str]] = {
        "PRIMARY",
        "FOREIGN",
        "UNIQUE",
        "CONSTRAINT",
        "KEY",
        "INDEX",
        "CHECK",
        "PARTITION",
        "PARTITIONED",
    }

    def _regex_fallback_parse(self, ddl_statement: str) -> TableStructure | None:
        """Extract table structure without relying on sqlglot's tokenizer.

        Used when sqlglot cannot produce a CREATE node, typically because a
        column name is a SQL reserved word (e.g. ``if``, ``on``). Parses the
        first balanced ``(...)`` block after the table name as the column list
        and appends any PARTITIONED BY columns.
        """
        name_match = re.match(
            r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
            ddl_statement,
            flags=re.IGNORECASE,
        )
        if not name_match:
            return None
        table_name = ".".join(part.strip('`"[]') for part in name_match.group(1).split("."))
        if not table_name:
            return None

        body = self._extract_first_paren_block(ddl_statement, name_match.end())
        if body is None:
            return None

        fields: list[FieldInfo] = []
        seen: set[str] = set()
        for part in self._split_columns(body):
            field = self._parse_single_column_def(part)
            if field is not None and field.name not in seen:
                fields.append(field)
                seen.add(field.name)

        for field in self._regex_partition_columns(ddl_statement):
            if field.name not in seen:
                fields.append(field)
                seen.add(field.name)

        if not fields:
            return None
        table_comment = self._extract_table_comment(ddl_statement)
        return TableStructure(table_name=table_name, fields=fields, table_comment=table_comment)

    def _extract_first_paren_block(self, text: str, start_at: int) -> str | None:
        """Return the content of the first balanced ``(...)`` at/after ``start_at``."""
        open_idx = text.find("(", start_at)
        if open_idx == -1:
            return None
        depth = 0
        quote: str | None = None
        for i in range(open_idx, len(text)):
            char = text[i]
            if quote is not None:
                if char == quote:
                    quote = None
                continue
            if char in ("'", '"', "`"):
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[open_idx + 1 : i]
        return None

    def _parse_single_column_def(self, col_text: str) -> FieldInfo | None:
        """Parse ``name type [constraints] [COMMENT '...']`` into a FieldInfo."""
        col_text = col_text.strip()
        if not col_text:
            return None

        comment_match = re.search(r"COMMENT\s+['\"](.+?)['\"]", col_text, re.IGNORECASE | re.DOTALL)
        comment = comment_match.group(1) if comment_match else None
        clean = re.sub(
            r"\s*COMMENT\s+['\"].*?['\"]", "", col_text, flags=re.IGNORECASE | re.DOTALL
        ).strip()

        parts = clean.split(None, 1)
        if not parts:
            return None
        name = parts[0].strip("`\"[]'")
        if not name or name.upper() in self._NON_COLUMN_TOKENS:
            return None

        col_type = parts[1].strip() if len(parts) > 1 else ""
        # Drop trailing column constraints so the type stays clean.
        col_type = re.sub(
            r"\s+(NOT\s+NULL|NULL|DEFAULT\s+.+|PRIMARY\s+KEY)\s*$",
            "",
            col_type,
            flags=re.IGNORECASE,
        ).strip()
        return FieldInfo(name=name, type=(col_type or "STRING").upper(), comment=comment)

    def _regex_partition_columns(self, ddl_text: str) -> list[FieldInfo]:
        """Extract PARTITIONED BY columns via regex (no sqlglot dependency)."""
        match = re.search(r"PARTITIONED\s+BY\s*\((.*?)\)", ddl_text, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        return self._parse_partition_block(match.group(1).strip())

    def _split_columns(self, text: str) -> list[str]:
        """Split column definitions by comma, respecting parentheses and quotes."""
        parts: list[str] = []
        depth = 0
        current: list[str] = []
        quote: str | None = None
        for char in text:
            if quote is not None:
                current.append(char)
                if char == quote:
                    quote = None
                continue
            if char in ("'", '"', "`"):
                quote = char
                current.append(char)
            elif char == "(":
                depth += 1
                current.append(char)
            elif char == ")":
                depth -= 1
                current.append(char)
            elif char == "," and depth == 0:
                parts.append("".join(current))
                current = []
            else:
                current.append(char)
        if current:
            parts.append("".join(current))
        return parts
