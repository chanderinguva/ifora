"""Loads and serves the connector definitions shipped in `definitions/` (repository files only; no administrator uploads, ADR 026)."""

import os
from functools import lru_cache
from typing import Dict, List

import yaml

from backend.app.connectors.schema import Action, Connector, DefinitionInvalid, validate_connector

_DIR = os.path.join(os.path.dirname(__file__), "definitions")


@lru_cache(maxsize=1)
def _load() -> Dict[str, Connector]:
    out: Dict[str, Connector] = {}
    for name in sorted(os.listdir(_DIR)):
        if not name.endswith(".yaml"):
            continue
        with open(os.path.join(_DIR, name), encoding="utf-8") as f:
            raw = yaml.safe_load(f)  # safe_load only: no object construction from the file
        try:
            c = validate_connector(raw)
        except DefinitionInvalid as e:
            raise DefinitionInvalid(f"{name}: {e}")
        if name != f"{c.id}.yaml":
            raise DefinitionInvalid(f"{name}: file name must be <id>.yaml")
        if c.id in out:
            raise DefinitionInvalid(f"{name}: duplicate connector id")
        out[c.id] = c
    return out


def all_connectors() -> List[Connector]:
    return list(_load().values())


def get(connector_id: str):
    return _load().get(connector_id)


def action_of(c: Connector, action_id: str) -> Action | None:
    return next((a for a in c.actions if a.id == action_id), None)


def public_view(c: Connector) -> dict:
    """What the admin API shows: no static headers' internals beyond names, never secrets (there are none in a definition)."""
    return {
        "id": c.id, "version": c.version, "name": c.name, "category": c.category, "description": c.description, "hosts": c.hosts,
        "auth": {"scheme": c.auth.scheme, "fields": [f.model_dump() for f in c.auth.fields]},
        "actions": [{
            "id": a.id, "label": a.label, "description": a.description, "method": a.method, "read_only": a.read_only, "idempotent": a.idempotent,
            "inputs": [i.model_dump() for i in a.inputs], "outputs": [o.key for o in a.outputs] + ["status_code", "ok"],
            "required_scopes": a.required_scopes, "scope_by_input": a.scope_by_input,
        } for a in c.actions],
    }
