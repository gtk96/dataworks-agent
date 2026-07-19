"""Contracts for tools invoked by the conversational Agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Protocol


class SideEffect(StrEnum):
    """The strongest external side effect a tool can produce."""

    NONE = "none"
    READ = "read"
    DEV_WRITE = "dev_write"
    DESTRUCTIVE = "destructive"
    PUBLISH = "publish"

    @property
    def can_write(self) -> bool:
        return self in {self.DEV_WRITE, self.DESTRUCTIVE, self.PUBLISH}


@dataclass(frozen=True)
class ToolContext:
    conversation_id: str
    state: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    recoverable: bool = True
    write_boundary_crossed: bool = False
    uncertain_write: bool = False

    @classmethod
    def ok(cls, message: str, *, data: dict[str, Any] | None = None) -> ToolResult:
        return cls(success=True, message=message, data=dict(data or {}))

    @classmethod
    def failure(
        cls,
        message: str,
        *,
        error_code: str = "tool_failed",
        data: dict[str, Any] | None = None,
        recoverable: bool = True,
        write_boundary_crossed: bool = False,
    ) -> ToolResult:
        return cls(
            success=False,
            message=message,
            data=dict(data or {}),
            error_code=error_code,
            recoverable=recoverable,
            write_boundary_crossed=write_boundary_crossed,
        )

    def for_effect(self, effect: SideEffect) -> ToolResult:
        uncertain = bool(self.write_boundary_crossed and effect.can_write and not self.success)
        return replace(
            self,
            uncertain_write=uncertain,
            recoverable=False if uncertain else self.recoverable,
        )


class AgentTool(Protocol):
    name: str
    side_effect: SideEffect

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...
