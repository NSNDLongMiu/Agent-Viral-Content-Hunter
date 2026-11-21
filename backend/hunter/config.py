"""Local TOML settings, environment overrides, and the zero-cost policy."""

import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

PASSWORD_HASH_PATTERN = re.compile(r"scrypt\$[0-9a-f]{32}\$[0-9a-f]{64}")


class SettingsError(ValueError):
    """Invalid startup configuration."""


class PaidAPIForbidden(RuntimeError):
    """The integration's cost is paid or unverified."""


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class BudgetSettings(ConfigModel):
    allow_paid_api: Literal[False] = False

    @field_validator("allow_paid_api", mode="before")
    @classmethod
    def enforce_zero_cost(cls, value: object) -> object:
        if value is not False:
            raise ValueError("Paid APIs are disabled by policy")
        return value

    def require_allowed(self, *, incurs_cost: bool | None) -> None:
        """Call before external I/O. Only a verified zero incremental cost is allowed."""
        if incurs_cost is not False:
            raise PaidAPIForbidden("The zero-cost policy requires verified free access")


class QueueSettings(ConfigModel):
    lease_seconds: int = Field(default=60, gt=0)
    retry_base_seconds: int = Field(default=5, gt=0)
    claude: int = Field(default=1, ge=0)
    codex: int = Field(default=2, ge=0)
    gemini: int = Field(default=2, ge=0)
    local: int = Field(default_factory=lambda: max(1, (os.cpu_count() or 1) // 4), ge=0)
    collector: int = Field(default=2, ge=0)


class RetentionSettings(ConfigModel):
    days: int = Field(default=90, ge=1, le=36500)


class AuthSettings(ConfigModel):
    admin_password_hash: SecretStr | None = None
    claude_service_token: SecretStr | None = Field(default=None, min_length=32)
    session_ttl_seconds: int = Field(default=28800, gt=0)

    @field_validator("admin_password_hash")
    @classmethod
    def check_password_hash(cls, value: SecretStr | None) -> SecretStr | None:
        if value and not PASSWORD_HASH_PATTERN.fullmatch(value.get_secret_value()):
            raise ValueError("Use the configured scrypt password hash format")
        return value

    @field_validator("claude_service_token")
    @classmethod
    def check_service_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value and not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value.get_secret_value()):
            raise ValueError("Use ASCII bearer-token characters")
        return value


class Settings(ConfigModel):
    database_path: Path = Path("backend/data/hunter.sqlite3")
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)


def _project_root() -> Path:
    for location in (Path.cwd(), *Path.cwd().parents):
        if (location / "config" / "settings.example.toml").is_file():
            return location
    return Path.cwd()


def load_settings(path: Path | None = None, *, environ: Mapping[str, str] | None = None) -> Settings:
    """Load TOML, then apply HUNTER_SECTION__FIELD and HUNTER_DATABASE_PATH."""
    env = os.environ if environ is None else environ
    root = _project_root()
    explicit = path or env.get("HUNTER_CONFIG")
    config_path = Path(explicit) if explicit else root / "config" / "settings.local.toml"
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8")) if (
            explicit or config_path.exists()
        ) else {}
        for section, model in (
            ("budget", BudgetSettings),
            ("queue", QueueSettings),
            ("retention", RetentionSettings),
            ("auth", AuthSettings),
        ):
            for field in model.model_fields:
                value = env.get(f"HUNTER_{section.upper()}__{field.upper()}")
                if value is None:
                    continue
                if section == "budget":
                    value = {"true": True, "false": False}.get(value.lower(), value)
                data.setdefault(section, {})[field] = value
        if "HUNTER_DATABASE_PATH" in env:
            data["database_path"] = env["HUNTER_DATABASE_PATH"]
        settings = Settings.model_validate(data)
    except (OSError, ValueError, TypeError) as error:
        fields = ""
        if isinstance(error, ValidationError):
            fields = " (" + ", ".join(
                ".".join(str(part) for part in item["loc"])
                for item in error.errors(include_input=False) if item["type"] != "extra_forbidden"
            ) + ")"
        raise SettingsError(f"Invalid Hunter settings{fields}") from None
    if not settings.database_path.is_absolute():
        settings = settings.model_copy(update={"database_path": root / settings.database_path})
    return settings
