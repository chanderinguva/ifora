"""SCIM error type and media type (RFC 7644 3.12)."""

from typing import Optional

ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
MEDIA_TYPE = "application/scim+json"


class ScimError(Exception):
    def __init__(self, status: int, detail: str, scim_type: Optional[str] = None, headers: Optional[dict] = None):
        super().__init__(detail)
        self.status, self.detail, self.scim_type, self.headers = status, detail, scim_type, headers

    def body(self) -> dict:
        out = {"schemas": [ERROR_SCHEMA], "status": str(self.status), "detail": self.detail}
        if self.scim_type:
            out["scimType"] = self.scim_type
        return out


def invalid_value(detail: str) -> ScimError:
    return ScimError(400, detail, "invalidValue")


def invalid_syntax(detail: str) -> ScimError:
    return ScimError(400, detail, "invalidSyntax")


def invalid_path(detail: str) -> ScimError:
    return ScimError(400, detail, "invalidPath")


def no_target(detail: str) -> ScimError:
    return ScimError(400, detail, "noTarget")


def uniqueness(detail: str) -> ScimError:
    return ScimError(409, detail, "uniqueness")


def mutability(detail: str, status: int = 400) -> ScimError:
    return ScimError(status, detail, "mutability")


def not_found(detail: str = "Resource not found") -> ScimError:
    return ScimError(404, detail)
