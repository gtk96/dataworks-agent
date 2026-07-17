"""Skill Registry — 可插拔的能力注册系统。

扫描 skills/ 目录，加载所有 .md 文件，提供基于关键词 + LLM 语义的
意图匹配。Skill 文件支持 YAML frontmatter 描述 + Markdown 指令。

使用方式:
    registry = SkillRegistry(skills_dir=Path("skills/"))
    matches = registry.match("帮我建一张 DWD 订单明细表")
    # => [Skill(name="modeling", ...), ...]

Skill 文件格式:
    ---
    name: 智能问数
    description: 通过自然语言查询数仓指标，自动解析口径、生成 SQL、返回图表
    triggers: ["查询", "指标", "GMV", "订单量", "ask_data"]
    tools: [query_metric, generate_chart, clarify_caliber]
    priority: 5
    ---
    当用户询问指标、数据、趋势、对比时激活此 Skill。
    Agent 会自动注入语义层上下文。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """一个可插拔的能力描述。"""

    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    priority: int = 5  # 1-10，越高越优先
    content: str = ""  # Markdown 指令正文
    category: str = "general"  # modeling / query / diagnosis / governance / custom

    def match_keywords(self, text: str) -> int:
        """基于关键词匹配，返回匹配分数。"""
        text_lower = text.lower()
        score = 0
        for trigger in self.triggers:
            if trigger.lower() in text_lower:
                score += len(trigger)  # 越长越精确
        return score


class SkillRegistry:
    """Skill 注册中心。

    启动时扫描 skills/ 目录，加载所有 .md 文件。
    运行时提供意图匹配。
    """

    def __init__(self, skills_dir: Path | str | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        self._skills_dir = Path(skills_dir) if skills_dir else None
        if self._skills_dir:
            self._scan(self._skills_dir)
        # 注册内置 Skill
        self._register_builtin_skills()

    def _scan(self, skills_dir: Path) -> None:
        """扫描目录，加载所有 .md 文件。"""
        if not skills_dir.exists():
            logger.info("Skills directory not found: %s", skills_dir)
            return
        for md_file in sorted(skills_dir.glob("*.md")):
            try:
                skill = self._parse(md_file)
                if skill:
                    self._skills[skill.name] = skill
                    logger.info("Loaded skill: %s (priority=%d, triggers=%d)",
                                skill.name, skill.priority, len(skill.triggers))
            except Exception as e:
                logger.warning("Failed to load skill %s: %s", md_file.name, e)

    def _parse(self, path: Path) -> Skill | None:
        """解析 Skill Markdown 文件。"""
        content = path.read_text(encoding="utf-8")

        # 解析 YAML frontmatter
        fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            body = fm_match.group(2)
        else:
            fm_text = ""
            body = content

        # 简单 YAML 解析
        name = ""
        description = ""
        triggers: list[str] = []
        tools: list[str] = []
        priority = 5
        category = "general"

        for line in fm_text.strip().split('\n'):
            line = line.strip()
            if line.startswith('name:'):
                name = line.split(':', 1)[1].strip().strip('"').strip("'")
            elif line.startswith('description:'):
                description = line.split(':', 1)[1].strip().strip('"').strip("'")
            elif line.startswith('triggers:'):
                raw = line.split(':', 1)[1].strip()
                triggers = [t.strip().strip('"').strip("'") for t in re.findall(r'"([^"]+)"', raw)
                           if '"' in raw]
                if not triggers:
                    triggers = [t.strip() for t in raw.strip('[]').split(',') if t.strip()]
            elif line.startswith('tools:'):
                raw = line.split(':', 1)[1].strip()
                tools = [t.strip().strip('"').strip("'") for t in re.findall(r'"([^"]+)"', raw)
                        if '"' in raw]
                if not tools:
                    tools = [t.strip() for t in raw.strip('[]').split(',') if t.strip()]
            elif line.startswith('priority:'):
                try:
                    priority = int(line.split(':', 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith('category:'):
                category = line.split(':', 1)[1].strip().strip('"').strip("'")

        if not name:
            name = path.stem

        return Skill(
            name=name,
            description=description,
            triggers=triggers,
            tools=tools,
            priority=priority,
            content=body,
            category=category,
        )

    def _register_builtin_skills(self) -> None:
        """注册内置 Skill（不依赖外部文件）。"""
        builtins = [
            Skill(
                name="modeling",
                description="全链路数仓建模：ODS→DWD→DIM→DWS 分层建表、SQL 生成、调度配置",
                triggers=["建模", "建表", "create", "建模", "ods", "dwd", "dim", "dws",
                          "forward_modeling", "reverse_modeling", "ods_dwd"],
                tools=["create_table", "generate_ddl", "generate_dml", "create_node",
                       "configure_schedule", "deploy_node"],
                priority=8,
                category="modeling",
                content="# 建模 Skill\n全链路数仓建模，支持正向和逆向。",
            ),
            Skill(
                name="query",
                description="智能问数：自然语言查询指标，自动解析口径、生成 SQL、返回图表",
                triggers=["查询", "指标", "GMV", "订单量", "ask_data", "query",
                          "查询指标", "数据查询", "看数据", "有多少", "统计"],
                tools=["query_metric", "generate_chart", "clarify_caliber", "execute_query"],
                priority=7,
                category="query",
                content="# 问数 Skill\n通过自然语言查询数仓指标。",
            ),
            Skill(
                name="diagnosis",
                description="异常排查：任务失败诊断、血缘影响面分析、根因定位",
                triggers=["诊断", "排查", "失败", "异常", "diagnose", "报错",
                          "为什么失败", "影响范围", "根因", "trace"],
                tools=["diagnose_task", "get_lineage", "get_upstream_tasks", "query_logs"],
                priority=7,
                category="diagnosis",
                content="# 诊断 Skill\n任务异常排查和根因分析。",
            ),
            Skill(
                name="governance",
                description="数仓治理：词根校验、命名规范、DDL 检查、血缘管理",
                triggers=["治理", "词根", "规范", "命名", "governance", "校验",
                          "DDL 检查", "血缘", "bus_matrix", "word_root"],
                tools=["check_ddl", "check_word_root", "get_lineage", "get_bus_matrix"],
                priority=6,
                category="governance",
                content="# 治理 Skill\n数仓规范和治理。",
            ),
            Skill(
                name="cookie_manage",
                description="Cookie 管理：提取、刷新、健康检查",
                triggers=["Cookie", "cookie", "登录", "login", "鉴权", "认证"],
                tools=["extract_cookie", "refresh_cookie", "check_cookie_health"],
                priority=3,
                category="general",
                content="# Cookie 管理 Skill\nCookie 提取和刷新。",
            ),
        ]
        for skill in builtins:
            self._skills[skill.name] = skill
            logger.info("Registered builtin skill: %s", skill.name)

    def match(self, user_input: str, limit: int = 3) -> list[Skill]:
        """匹配用户输入相关的 Skill。

        基于关键词匹配 + 优先级排序。
        """
        if not user_input:
            return []

        scored: list[tuple[int, Skill]] = []
        for name, skill in self._skills.items():
            score = skill.match_keywords(user_input)
            if score > 0:
                scored.append((score, skill))

        # 按分数降序 + 优先级降序
        scored.sort(key=lambda x: (x[0], x[1].priority), reverse=True)

        return [s for _, s in scored[:limit]]

    def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_skills(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "triggers": s.triggers,
                "tools": s.tools,
                "priority": s.priority,
                "category": s.category,
            }
            for s in self._skills.values()
        ]

    @property
    def skill_names(self) -> list[str]:
        return list(self._skills.keys())
