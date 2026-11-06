"""/ServiceProviderConfig, /ResourceTypes, /Schemas (RFC 7644 4). Says plainly what is not supported."""

from typing import Any, Dict, List

from backend.app.scim.mapping import (
    ENTERPRISE_URN, GROUP_URN, PROFILE_URN, RT_URN, SCHEMA_URN, SPC_URN, USER_URN, base_url,
)

MAX_RESULTS = 200


def service_provider_config() -> Dict[str, Any]:
    return {
        "schemas": [SPC_URN],
        "documentationUri": "https://github.com/chanderinguva/identityforge/blob/main/docs/architecture/007-scim-server.md",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": MAX_RESULTS},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": True},
        "authenticationSchemes": [{
            "type": "oauthbearertoken", "name": "Bearer token", "primary": True,
            "description": "Admin-issued, per-tenant bearer token (Authorization: Bearer idf_scim_...)",
            "specUri": "https://www.rfc-editor.org/rfc/rfc6750",
        }],
        "meta": {"resourceType": "ServiceProviderConfig", "location": f"{base_url()}/ServiceProviderConfig"},
    }


def resource_types() -> List[Dict[str, Any]]:
    return [
        {
            "schemas": [RT_URN], "id": "User", "name": "User", "endpoint": "/Users", "description": "User account",
            "schema": USER_URN,
            "schemaExtensions": [
                {"schema": ENTERPRISE_URN, "required": False},
                {"schema": PROFILE_URN, "required": False},
            ],
            "meta": {"resourceType": "ResourceType", "location": f"{base_url()}/ResourceTypes/User"},
        },
        {
            "schemas": [RT_URN], "id": "Group", "name": "Group", "endpoint": "/Groups", "description": "Group",
            "schema": GROUP_URN,
            "meta": {"resourceType": "ResourceType", "location": f"{base_url()}/ResourceTypes/Group"},
        },
    ]


def _a(name, typ="string", *, multi=False, required=False, mutability="readWrite", unique="none", case=False,
       subs=None, desc="") -> Dict[str, Any]:
    out = {
        "name": name, "type": typ, "multiValued": multi, "required": required, "caseExact": case,
        "mutability": mutability, "returned": "default", "uniqueness": unique, "description": desc,
    }
    if subs:
        out["subAttributes"] = subs
    return out


def schemas() -> List[Dict[str, Any]]:
    contact = [_a("value"), _a("type"), _a("primary", "boolean"), _a("display")]
    meta = lambda sid: {"resourceType": "Schema", "location": f"{base_url()}/Schemas/{sid}"}  # noqa: E731
    return [
        {
            "schemas": [SCHEMA_URN], "id": USER_URN, "name": "User", "description": "IdentityForge user", "meta": meta(USER_URN),
            "attributes": [
                _a("userName", required=True, unique="server", desc="Stored lower-case in users.username"),
                _a("externalId", desc="The IdP's identifier for this user"),
                _a("name", "complex", subs=[_a("givenName", required=True), _a("familyName", required=True), _a("formatted", mutability="readOnly")]),
                _a("displayName", mutability="readOnly"),
                _a("emails", "complex", multi=True, required=True, subs=contact, desc="Only one address is stored (primary, else work, else first)"),
                _a("phoneNumbers", "complex", multi=True, subs=contact, desc="Only one number is stored; maps to profile attribute 'phone'"),
                _a("title"), _a("locale"), _a("timezone"),
                _a("active", "boolean", desc="false deactivates the account; it is never deleted"),
                _a("groups", "complex", multi=True, mutability="readOnly", subs=[_a("value"), _a("display"), _a("$ref", "reference")]),
            ],
        },
        {
            "schemas": [SCHEMA_URN], "id": ENTERPRISE_URN, "name": "EnterpriseUser", "description": "Enterprise extension",
            "meta": meta(ENTERPRISE_URN),
            "attributes": [
                _a("employeeNumber", desc="Profile attribute employee_id"), _a("costCenter", desc="Profile attribute cost_center"),
                _a("department", desc="Profile attribute department"),
                _a("manager", "complex", subs=[_a("value", desc="Stored as given, not resolved"), _a("displayName", mutability="readOnly")]),
            ],
        },
        {
            "schemas": [SCHEMA_URN], "id": PROFILE_URN, "name": "IdentityForgeProfile",
            "description": "Any other attribute defined in the Profile editor, addressed by its key. Types are enforced by the catalog.",
            "meta": meta(PROFILE_URN), "attributes": [],
        },
        {
            "schemas": [SCHEMA_URN], "id": GROUP_URN, "name": "Group", "description": "IdentityForge group", "meta": meta(GROUP_URN),
            "attributes": [
                _a("displayName", required=True, unique="server"), _a("externalId"),
                _a("members", "complex", multi=True, subs=[_a("value", desc="User id"), _a("display", mutability="readOnly"), _a("$ref", "reference", mutability="readOnly")],
                   desc="Memberships created by group rules cannot be removed through SCIM"),
            ],
        },
    ]
