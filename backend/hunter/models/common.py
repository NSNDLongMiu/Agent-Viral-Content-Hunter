from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, HttpUrl, StringConstraints

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return value.astimezone(UTC)


def utc_iso(value: datetime) -> str:
    return as_utc(value).isoformat(timespec="microseconds")


def new_id() -> str:
    return uuid4().hex


def _public_url(value: HttpUrl) -> HttpUrl:
    if value.username is not None or value.password is not None:
        raise ValueError("Use a public URL without embedded credentials")
    return value


UtcDatetime = Annotated[AwareDatetime, AfterValidator(as_utc)]
PublicUrl = Annotated[HttpUrl, AfterValidator(_public_url)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")
