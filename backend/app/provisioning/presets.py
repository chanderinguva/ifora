"""Starting points shown in the 'Add application' dialog (Okta-style app catalogue, generic only)."""

REST_EXAMPLE = {
    "test": {"method": "GET", "path": "/health"},
    "find_user": {"method": "GET", "path": "/users?email={{userName}}", "id_path": "items.0.id"},
    "create_user": {"method": "POST", "path": "/users", "id_path": "id", "ok": [200, 201],
                    "body": {"email": "{{userName}}", "first_name": "{{name.givenName}}", "last_name": "{{name.familyName}}",
                             "title": "{{title}}", "active": "{{active}}"}},
    "update_user": {"method": "PUT", "path": "/users/{{id}}",
                    "body": {"email": "{{userName}}", "first_name": "{{name.givenName}}", "last_name": "{{name.familyName}}",
                             "title": "{{title}}", "active": "{{active}}"}},
    "deactivate_user": {"method": "POST", "path": "/users/{{id}}/deactivate"},
    "reactivate_user": {"method": "POST", "path": "/users/{{id}}/activate"},
    "delete_user": {"method": "DELETE", "path": "/users/{{id}}"},
}

PRESETS = [
    {"key": "scim-bearer", "name": "SCIM 2.0 application (bearer token)", "kind": "scim", "auth_type": "bearer",
     "description": "Any application with a SCIM 2.0 endpoint that accepts an API token (RFC 7644).",
     "options": {"update_style": "put", "deactivate": "patch", "push_groups": False}},
    {"key": "scim-basic", "name": "SCIM 2.0 application (basic auth)", "kind": "scim", "auth_type": "basic",
     "description": "SCIM 2.0 endpoint secured with a user name and password. Enter the secret as user:password.",
     "options": {"update_style": "put", "deactivate": "patch", "push_groups": False}},
    {"key": "scim-patch", "name": "SCIM 2.0 application (PATCH updates, groups)", "kind": "scim", "auth_type": "bearer",
     "description": "For applications that only accept PATCH for updates and manage membership through SCIM groups.",
     "options": {"update_style": "patch", "deactivate": "patch", "push_groups": True}},
    {"key": "rest-gateway", "name": "REST application (SCIM gateway)", "kind": "rest", "auth_type": "bearer",
     "description": "An application with its own REST API. Ifora turns provisioning into the calls you describe.",
     "options": {"deactivate": "patch", "push_groups": False}, "rest_config": REST_EXAMPLE},
]
