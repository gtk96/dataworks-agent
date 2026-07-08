"""TemplateLoader — 加载内置数仓规范与词根字典。"""

from __future__ import annotations

from dataworks_agent.standards.loader import (
    list_standard_documents,
    load_standard_document,
    load_word_root_entries,
)


class TemplateLoader:
    """加载建模规范文件（不再依赖外部 dw-modeling-template 路径）。"""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def load_standard(self, name: str) -> str:
        if name in self._cache:
            return self._cache[name]
        try:
            content = load_standard_document(name)
        except (KeyError, FileNotFoundError):
            content = ""
        self._cache[name] = content
        return content

    def load_word_root_dict(self) -> list[dict]:
        return [
            {
                "column_name": item["column_name"],
                "column_desc": item.get("column_desc", ""),
                "is_digit": 1 if item.get("is_digit") else 0,
            }
            for item in load_word_root_entries()
        ]

    def get_datawarehouse_standards(self) -> str:
        return self.load_standard("data-warehouse-standards")

    def get_field_naming_standards(self) -> str:
        return self.load_standard("field-naming-standards")

    def get_hologres_standards(self) -> str:
        return self.load_standard("hologres-naming-standards")

    def get_sql_rules(self) -> str:
        return self.load_standard("sql-development-rules")

    def list_documents(self) -> list[dict[str, str]]:
        return list_standard_documents()


template_loader = TemplateLoader()
