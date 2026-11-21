from enum import StrEnum
from typing import Protocol

from pydantic import Field, JsonValue, field_validator, model_validator

from hunter.models import AIName
from hunter.models.common import Model, NonEmpty, UtcDatetime


class AIStatus(StrEnum):
    OK = "OK"
    AUTH_LOST = "AUTH_LOST"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class AIHealth(Model):
    name: AIName
    status: AIStatus
    available: bool
    quota_exhausted: bool = False
    last_error: NonEmpty | None = None
    checked_at: UtcDatetime


class AITask(Model):
    id: NonEmpty
    instructions: NonEmpty
    input: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)

    @field_validator("output_schema")
    @classmethod
    def check_schema(cls, schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
        from jsonschema import Draft202012Validator, SchemaError

        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError:
            raise ValueError("The output schema must be valid JSON Schema Draft 2020-12") from None
        return schema


class AIResult(Model):
    status: AIStatus
    output: dict[str, JsonValue] | None = None
    error: NonEmpty | None = None

    @model_validator(mode="after")
    def check_status(self) -> "AIResult":
        if (self.status == AIStatus.OK) != (self.output is not None):
            raise ValueError("Structured output is required for OK and reserved for OK")
        return self

    @classmethod
    def success(cls, task: AITask, output: dict[str, JsonValue]) -> "AIResult":
        return cls(status=AIStatus.OK, output=output).validate_for(task)

    def validate_for(self, task: AITask) -> "AIResult":
        """Validate successful output against the task schema without fetching remote references."""
        from jsonschema import Draft202012Validator, FormatChecker, exceptions
        from referencing import Registry
        from referencing.exceptions import Unresolvable

        if self.status == AIStatus.OK:
            validator = Draft202012Validator(
                task.output_schema, registry=Registry(), format_checker=FormatChecker()
            )
            try:
                validator.validate(self.output)
            except (exceptions.ValidationError, Unresolvable):
                raise ValueError("AI output failed task schema validation") from None
        return self


class AIWorker(Protocol):
    """Runs structured tasks through an approved zero-cost integration."""

    @property
    def name(self) -> AIName:
        """One of claude, codex, gemini or local."""
        ...

    async def run(self, task: AITask) -> AIResult:
        """Map real failures to statuses and build successful results with AIResult.success."""
        ...

    def health(self) -> AIHealth:
        """Return observed access and quota status with a credential-free diagnostic."""
        ...
