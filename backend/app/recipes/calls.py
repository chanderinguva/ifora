"""Callable recipes (ADR 021 section 3): a recipe whose trigger is "Called by another recipe" declares inputs and
outputs; a Call recipe step in another recipe runs its published version as a child job and receives the returned data."""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.recipes.models import Recipe, RecipeJob, RecipeVersion

MAX_CALL_DEPTH = 5
POLL_SECONDS = 30      # fallback; a finishing child wakes its parent at once
TYPES = ("text", "number", "boolean", "list", "object")


def published_definition(db: Session, recipe: Recipe) -> Optional[dict]:
    if recipe.published_version is None:
        return None
    v = db.query(RecipeVersion).filter(RecipeVersion.recipe_id == recipe.id, RecipeVersion.version == recipe.published_version).first()
    return v.definition if v else None


def signature(definition: Optional[dict]) -> Optional[dict]:
    """{"inputs": [...], "outputs": [...]} of a callable definition, else None."""
    if not definition or definition["trigger"]["type"] != "call":
        return None
    cfg = definition["trigger"].get("config") or {}
    return {"inputs": cfg.get("inputs", []), "outputs": cfg.get("outputs", [])}


def callee(db: Session, recipe_id: int) -> Optional[tuple]:
    """(Recipe, published definition, signature) when the recipe can be called now, else None."""
    r = db.get(Recipe, recipe_id)
    if r is None or not r.enabled:
        return None
    d = published_definition(db, r)
    sig = signature(d)
    return (r, d, sig) if sig else None


def callable_recipes(db: Session) -> List[Dict[str, Any]]:
    out = []
    for r in db.query(Recipe).filter(Recipe.published_version.isnot(None), Recipe.enabled.is_(True)).order_by(Recipe.name):
        sig = signature(published_definition(db, r))
        if sig:
            out.append({"id": r.id, "name": r.name, **sig})
    return out


def check_inputs(sig: dict, given: Dict[str, Any]) -> None:
    """Raises ValueError with a plain message when the call does not match the callee's declared inputs."""
    declared = {i["name"]: i for i in sig["inputs"]}
    extra = sorted(set(given) - set(declared))
    if extra:
        raise ValueError(f"the recipe has no input '{extra[0]}'")
    for name, i in declared.items():
        if i.get("required", True) and name not in given:
            raise ValueError(f"input '{name}' is required")


def coerce(sig: dict, values: Dict[str, Any]) -> Dict[str, Any]:
    """Text typed into a number or yes/no input is converted ("21" -> 21); anything else is left for check_values."""
    types = {i["name"]: i["type"] for i in sig["inputs"]}
    out = dict(values)
    for k, v in values.items():
        if not isinstance(v, str):
            continue
        if types.get(k) == "number":
            try:
                out[k] = int(v) if v.strip().lstrip("-").isdigit() else float(v)
            except ValueError:
                pass
        elif types.get(k) == "boolean" and v.strip().lower() in ("true", "false"):
            out[k] = v.strip().lower() == "true"
    return out


def check_values(sig: dict, values: Dict[str, Any]) -> None:
    """Run time: each value must have the declared type (a number is not text)."""
    for i in sig["inputs"]:
        if i["name"] not in values:
            continue
        v, t = values[i["name"]], i["type"]
        ok = {"text": isinstance(v, str), "number": isinstance(v, (int, float)) and not isinstance(v, bool),
              "boolean": isinstance(v, bool), "list": isinstance(v, list), "object": isinstance(v, dict)}[t]
        if not ok:
            raise ValueError(f"input '{i['name']}' must be {'an' if t in ('object',) else 'a'} {t}")


def callers_of(db: Session, recipe_id: int) -> List[Dict[str, Any]]:
    """Recipes whose draft or published definition calls this one (shown before a callee is changed)."""
    found = []
    for r in db.query(Recipe).all():
        defs = [r.draft] if getattr(r, "draft", None) else []
        pub = published_definition(db, r)
        if pub:
            defs.append(pub)
        for d in defs:
            if _calls(d.get("steps", []) + d.get("on_error", []), recipe_id):
                found.append({"id": r.id, "name": r.name})
                break
    return found


def _calls(steps: list, recipe_id: int) -> bool:
    for s in steps:
        if s.get("type") == "call_recipe" and (s.get("config") or {}).get("recipe_id") == recipe_id:
            return True
        if _calls((s.get("then") or []) + (s.get("else") or []), recipe_id):
            return True
    return False
