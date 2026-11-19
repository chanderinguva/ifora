"""Application templates (IFORA-30): static, validated data that turns a sign-on mode, a provisioning preset and a checklist into one
guided create. Repository files only; nothing is fetched at load and nothing is executable (same rule as connector definitions)."""

import os
import re
from functools import lru_cache
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.connectors import registry as connectors
from backend.app.provisioning.presets import PRESETS

_DIR = os.path.join(os.path.dirname(__file__), "definitions")
_KEY = re.compile(r"^[a-z][a-z0-9-]{1,40}$")

# What an administrator may be asked for, and which sign-on / provisioning settings each completes.
FIELD_KEYS = {"redirect_uri", "sp_entity_id", "acs_url", "base_url", "secret", "launch_url"}


class TemplateInvalid(ValueError):
    pass


class TField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str = Field(..., min_length=1, max_length=100)
    help: str = Field("", max_length=300)
    placeholder: str = Field("", max_length=200)  # a hint shown in the input, never submitted and never a wildcard
    secret: bool = False


class Oidc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["web", "spa", "native"] = "web"


class Saml(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_id_format: Literal["email", "persistent", "username"] = "email"
    signing: Literal["assertion", "response", "both"] = "both"  # signed assertions by default


class Provisioning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str
    base_url: Optional[str] = None  # fixed endpoint, when the vendor has one; otherwise the administrator supplies it
    mapping: List[Dict[str, str]] = Field(default_factory=list)


class Template(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    version: int = 1
    name: str = Field(..., min_length=1, max_length=100)
    category: str = Field(..., min_length=1, max_length=40)
    description: str = Field(..., min_length=1, max_length=400)
    connector: Optional[str] = None  # a shipped connector this app pairs with for recipes
    sign_on: Literal["oidc", "saml", "none"]
    oidc: Optional[Oidc] = None
    saml: Optional[Saml] = None
    provisioning: Optional[Provisioning] = None
    fields: List[TField] = Field(default_factory=list)
    checklist: List[str] = Field(default_factory=list)


def _clean(*values: Optional[str]) -> bool:
    return all("*" not in (v or "") for v in values)


def validate_template(raw) -> Template:
    try:
        t = Template.model_validate(raw)
    except ValidationError as e:
        raise TemplateInvalid(str(e).splitlines()[1] if len(str(e).splitlines()) > 1 else "invalid") from None
    if not _KEY.match(t.key):
        raise TemplateInvalid("key must be lowercase letters, digits and dashes")
    if t.connector and connectors.get(t.connector) is None:
        raise TemplateInvalid(f"unknown connector '{t.connector}'")
    keys = [f.key for f in t.fields]
    if len(set(keys)) != len(keys):
        raise TemplateInvalid("duplicate field key")
    bad = [k for k in keys if k not in FIELD_KEYS]
    if bad:
        raise TemplateInvalid(f"unknown field '{bad[0]}'")
    for f in t.fields:
        if not _clean(f.placeholder, f.help):
            raise TemplateInvalid(f"field '{f.key}': a wildcard is never allowed in a redirect or ACS pattern")
        if f.key == "secret" and not f.secret:
            raise TemplateInvalid("the secret field must be marked secret: true")
    need = set()
    if t.sign_on == "oidc":
        if t.oidc is None or t.saml is not None:
            raise TemplateInvalid("an OIDC template needs an oidc block and no saml block")
        need |= {"redirect_uri"}
    elif t.sign_on == "saml":
        if t.saml is None or t.oidc is not None:
            raise TemplateInvalid("a SAML template needs a saml block and no oidc block")
        need |= {"sp_entity_id", "acs_url"}
    elif t.oidc is not None or t.saml is not None:
        raise TemplateInvalid("sign_on none takes no oidc or saml block")
    if t.provisioning is not None:
        p = t.provisioning
        if next((x for x in PRESETS if x["key"] == p.preset), None) is None:
            raise TemplateInvalid(f"unknown provisioning preset '{p.preset}'")
        need |= {"secret"}
        if p.base_url is None:
            need |= {"base_url"}
        elif not p.base_url.startswith("https://") or not _clean(p.base_url):
            raise TemplateInvalid("a fixed base_url must be an https URL without a wildcard")
    elif t.sign_on == "none":
        raise TemplateInvalid("a template with no sign-on must provision")
    if not need <= set(keys):
        raise TemplateInvalid(f"missing field(s): {', '.join(sorted(need - set(keys)))}")
    extra = set(keys) - need - {"launch_url"}
    if extra:
        raise TemplateInvalid(f"field '{sorted(extra)[0]}' does not apply to this template")
    return t


@lru_cache(maxsize=1)
def _load() -> Dict[str, Template]:
    out: Dict[str, Template] = {}
    for name in sorted(os.listdir(_DIR)):
        if not name.endswith(".yaml"):
            continue
        with open(os.path.join(_DIR, name), encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        try:
            t = validate_template(raw)
        except TemplateInvalid as e:
            raise TemplateInvalid(f"{name}: {e}") from None
        if name != f"{t.key}.yaml":
            raise TemplateInvalid(f"{name}: file name must be <key>.yaml")
        if t.key in out:
            raise TemplateInvalid(f"{name}: duplicate key")
        out[t.key] = t
    return out


def all_templates() -> List[Template]:
    return list(_load().values())


def get(key: str) -> Optional[Template]:
    return _load().get(key)


def public_view(t: Template) -> dict:
    return {
        "key": t.key, "name": t.name, "category": t.category, "description": t.description, "connector": t.connector, "sign_on": t.sign_on,
        "oidc_type": t.oidc.type if t.oidc else None, "provisioning": bool(t.provisioning), "fields": [f.model_dump() for f in t.fields],
        "checklist": t.checklist,
    }
