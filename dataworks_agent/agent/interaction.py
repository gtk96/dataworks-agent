"""Structured interaction protocol for recoverable Agent conversations."""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class InteractionExpiredError(ValueError):
    """Raised when an answer targets an interaction that is no longer active."""

    def __init__(self, message: str, *, current: PendingInteraction | None = None) -> None:
        super().__init__(message)
        self.current = current


class InteractionOption(BaseModel):
    """One server-owned selectable answer."""

    id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=1000)
    value: Any = None
    description: str = Field(default="", max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)
    layer: str = ""


class PendingInteraction(BaseModel):
    """The single currently actionable question for one conversation."""

    interaction_id: str = Field(min_length=1, max_length=128)
    type: Literal["single_select", "confirm", "free_text"] = "single_select"
    purpose: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=4000)
    options: list[InteractionOption] = Field(default_factory=list)
    allow_custom_input: bool = True
    custom_input_placeholder: str = Field(default="", max_length=1000)
    status: Literal["pending", "answered", "expired", "cancelled"] = "pending"
    state_version: int = Field(ge=0)


class InteractionAnswer(BaseModel):
    """A click or custom-text answer to a pending interaction."""

    interaction_id: str = Field(min_length=1, max_length=128)
    option_id: str | None = Field(default=None, min_length=1, max_length=128)
    custom_text: str | None = Field(default=None, min_length=1, max_length=10000)
    state_version: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_answer_mode(self) -> InteractionAnswer:
        has_option = bool(self.option_id)
        has_custom = bool(self.custom_text and self.custom_text.strip())
        if has_option == has_custom:
            raise ValueError("exactly one of option_id or custom_text is required")
        if self.custom_text is not None:
            self.custom_text = self.custom_text.strip()
        return self


def _option_payload(
    *, purpose: str, option_type: str, value: Any, explicit: dict[str, Any]
) -> dict[str, Any]:
    if explicit:
        return dict(explicit)
    if purpose == "select_table" or option_type == "pick_table":
        table = str(value or "").strip()
        if table:
            return {
                "params": {"table_name": table},
                "selected_resources": {"table": table},
            }
    if purpose == "select_layer":
        layer = str(value or "").strip().lower()
        if layer:
            return {"params": {"layer": layer}}
    return {"value": value} if value not in (None, "") else {}


def build_interaction(
    data: dict[str, Any], *, purpose: str, state_version: int
) -> PendingInteraction | None:
    """Normalize existing option_chips/next_actions into one interaction."""

    existing = data.get("interaction")
    if isinstance(existing, dict):
        payload = dict(existing)
        payload.setdefault("purpose", purpose)
        payload.setdefault("state_version", state_version)
        payload.setdefault("interaction_id", f"int_{uuid4().hex[:12]}")
        payload.setdefault("allow_custom_input", True)
        return PendingInteraction.model_validate(payload)

    raw_options = data.get("option_chips") or data.get("next_actions") or []
    options: list[InteractionOption] = []
    allow_custom_input = bool(data.get("allow_custom_input", True))
    placeholder = str(data.get("custom_input_hint") or "")

    for index, raw in enumerate(raw_options):
        if not isinstance(raw, dict):
            continue
        option_type = str(raw.get("type") or "")
        if option_type == "free_text" or raw.get("requires_custom_input"):
            allow_custom_input = True
            placeholder = str(raw.get("placeholder") or placeholder)
            continue
        label = str(raw.get("label") or raw.get("value") or "").strip()
        if not label:
            continue
        option_id = str(raw.get("id") or f"opt_{index}")
        value = raw.get("value", label)
        description = str(raw.get("description") or raw.get("subtitle") or "")
        explicit_payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        options.append(
            InteractionOption(
                id=option_id,
                label=label,
                value=value,
                description=description,
                payload=_option_payload(
                    purpose=purpose,
                    option_type=option_type,
                    value=value,
                    explicit=explicit_payload,
                ),
                layer=str(raw.get("layer") or ""),
            )
        )

    if not options and not allow_custom_input:
        return None

    questions = data.get("clarifying_questions") or []
    prompt = str(
        data.get("interaction_prompt")
        or (questions[0] if isinstance(questions, list) and questions else "")
        or data.get("message")
        or "请继续选择或补充信息。"
    )
    interaction_type: Literal["single_select", "confirm", "free_text"]
    if str(data.get("interaction_type") or "") == "confirm":
        interaction_type = "confirm"
    elif options:
        interaction_type = "single_select"
    else:
        interaction_type = "free_text"

    return PendingInteraction(
        interaction_id=f"int_{uuid4().hex[:12]}",
        type=interaction_type,
        purpose=purpose,
        prompt=prompt,
        options=options,
        allow_custom_input=allow_custom_input,
        custom_input_placeholder=placeholder,
        state_version=state_version,
    )


def resolve_interaction_answer(
    pending: PendingInteraction, answer: InteractionAnswer
) -> dict[str, Any]:
    """Resolve an answer using only the active server-owned interaction."""

    if (
        pending.status != "pending"
        or answer.interaction_id != pending.interaction_id
        or answer.state_version != pending.state_version
    ):
        raise InteractionExpiredError("当前候选已经更新，请根据最新选项继续。", current=pending)

    if answer.custom_text is not None:
        if not pending.allow_custom_input:
            raise ValueError("custom input is not allowed for this interaction")
        return {"custom_text": answer.custom_text}

    option = next((item for item in pending.options if item.id == answer.option_id), None)
    if option is None:
        raise InteractionExpiredError("所选选项已失效，请根据最新选项继续。", current=pending)
    return dict(option.payload)
