"""Shared validation for profile attributes and passwords."""

import re
from typing import Any, Dict, Union

from pydantic import BaseModel, Field, field_validator

AttrValue = Union[str, int, float, bool, None]
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
MAX_ATTRS = 20
MAX_STR = 500

_LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")  # e.g. en, en-GB, pt-BR


def valid_timezone(value: str) -> bool:
    """An IANA zone name known to the server (e.g. America/Chicago). Free text is not accepted."""
    from zoneinfo import available_timezones

    return value in available_timezones()


def valid_locale(value: str) -> bool:
    return bool(_LOCALE.match(value))


def validate_attributes(value: Dict[str, Any]) -> Dict[str, AttrValue]:
    if len(value) > MAX_ATTRS:
        raise ValueError(f"at most {MAX_ATTRS} attributes allowed")
    for k, v in value.items():
        if not _KEY.match(k):
            raise ValueError("attribute keys must match [a-z][a-z0-9_]{0,49}")
        if not (v is None or isinstance(v, (str, int, float, bool))):
            raise ValueError("attribute values must be scalar")
        if isinstance(v, str) and len(v) > MAX_STR:
            raise ValueError(f"attribute values limited to {MAX_STR} characters")
    return value


def validate_password(value: str) -> str:
    if len(value) < 12:
        raise ValueError("password must be at least 12 characters")
    if len(value) > 128:
        raise ValueError("password must be at most 128 characters")
    if value.lower() == value or value.upper() == value or not any(c.isdigit() for c in value):
        raise ValueError("password must mix upper/lower case letters and include a digit")
    return value


class PasswordChange(BaseModel):
    current_password: str = Field(..., max_length=128)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return validate_password(v)
