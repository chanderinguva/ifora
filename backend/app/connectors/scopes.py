"""Required scopes are explicit metadata; unknown permissions are never claimed verified."""
import re


def parse_slack_scopes(headers):
    value = next((v for k, v in headers.items() if k.lower() == "x-oauth-scopes"), None)
    if value is None or not isinstance(value, str) or len(value) > 8000:
        return None
    parts = [s.strip() for s in value.split(",") if s.strip()]
    if any(not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", s) for s in parts):
        return None
    return sorted(set(parts))


def required_for(action, inputs=None):
    scopes = list(action.required_scopes)
    for key, choices in action.scope_by_input.items():
        default = next((i.default for i in action.inputs if i.key == key), "")
        value = str((inputs or {}).get(key, default))
        if key == "channel" and value[:1] in choices:
            value = value[:1]
        else:
            value = value.lower()
        if value in choices:
            scopes += choices[value]
    return sorted(set(scopes))


def action_available(action, granted, inputs=None):
    if granted is None:
        return True  # Show requirements and allow remote validation.
    return set(required_for(action, inputs)) <= set(granted)
