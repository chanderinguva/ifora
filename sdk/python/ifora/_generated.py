"""Generated from the IFora OpenAPI document by generate.py. Do not edit; run `python generate.py --spec …` instead."""

from typing import Any, Dict, List, Mapping, Optional

from ._client import Transport, path_arg

class _AccessRequests:
    """Endpoints in the `access_requests` section."""

    def __init__(self, t: Transport):
        self._t = t

    def get_access_requests(self, *, status: Optional[str] = None) -> Any:
        """GET /api/v1/admin/access-requests

        List Requests"""
        return self._t.request("GET", "/api/v1/admin/access-requests", query={"status": status})

    def access_requests_approve(self, request_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/access-requests/{request_id}/approve

        Approve

        Body fields: note (str)"""
        return self._t.request("POST", f"/api/v1/admin/access-requests/{path_arg(request_id)}/approve", json=body)

    def access_requests_deny(self, request_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/access-requests/{request_id}/deny

        Deny

        Body fields: note (str)"""
        return self._t.request("POST", f"/api/v1/admin/access-requests/{path_arg(request_id)}/deny", json=body)

    def get_applications_self_service(self, app_id: int) -> Any:
        """GET /api/v1/admin/applications/{app_id}/self-service

        Get Self Service"""
        return self._t.request("GET", f"/api/v1/admin/applications/{path_arg(app_id)}/self-service")

    def set_applications_self_service(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/applications/{app_id}/self-service

        Put Self Service

        Body fields: enabled (bool, required), reason_required (bool)"""
        return self._t.request("PUT", f"/api/v1/admin/applications/{path_arg(app_id)}/self-service", json=body)

    def get_access_catalog(self) -> Any:
        """GET /api/v1/me/access/catalog

        Catalog

        Applications the user may ask for: self-service on, active, visible, and not already theirs.

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/access/catalog")

    def get_access_catalog_icon(self, app_id: int) -> Any:
        """GET /api/v1/me/access/catalog/{app_id}/icon

        Catalog Icon

        Needs a session: call client.login() first."""
        return self._t.request("GET", f"/api/v1/me/access/catalog/{path_arg(app_id)}/icon")

    def get_access_requests_me(self) -> Any:
        """GET /api/v1/me/access/requests

        My Requests

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/access/requests")

    def access_requests(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/access/requests

        Create Request

        Body fields: application_id (int, required), reason (str)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/access/requests", json=body)

    def access_requests_cancel(self, request_id: int) -> Any:
        """POST /api/v1/me/access/requests/{request_id}/cancel

        Cancel Request

        Needs a session: call client.login() first."""
        return self._t.request("POST", f"/api/v1/me/access/requests/{path_arg(request_id)}/cancel")

class _AccountRecovery:
    """Endpoints in the `account_recovery` section."""

    def __init__(self, t: Transport):
        self._t = t

    def change_expired_password(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/auth/change-expired-password

        Change Expired Password

        For accounts in `password_expired`: prove the current password, choose a new one, then sign in normally.

        Body fields: email (str, required), current_password (str, required), new_password (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/auth/change-expired-password", json=body)

    def forgot_password(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/auth/forgot-password

        Forgot Password

        Body fields: email (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/auth/forgot-password", json=body)

    def reset_password(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/auth/reset-password

        Reset Password

        Complete a reset or an invitation with the emailed token.

        Body fields: token (str, required), new_password (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/auth/reset-password", json=body)

class _AdminRoles:
    """Endpoints in the `admin_roles` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/admin/roles

        Catalog"""
        return self._t.request("GET", "/api/v1/admin/roles")

    def get_groups(self) -> Any:
        """GET /api/v1/admin/roles/groups

        Groups With Roles"""
        return self._t.request("GET", "/api/v1/admin/roles/groups")

    def get_groups_by_group_id(self, group_id: int) -> Any:
        """GET /api/v1/admin/roles/groups/{group_id}

        Get Group Roles"""
        return self._t.request("GET", f"/api/v1/admin/roles/groups/{path_arg(group_id)}")

    def set_groups(self, group_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/roles/groups/{group_id}

        Set Group Roles

        Every member of the group gets these roles. Only team and role based groups may carry roles; changing them takes effect on members' next request.

        Body fields: roles (List[Any])"""
        return self._t.request("PUT", f"/api/v1/admin/roles/groups/{path_arg(group_id)}", json=body)

    def get_users(self, user_id: int) -> Any:
        """GET /api/v1/admin/roles/users/{user_id}

        Get User Roles"""
        return self._t.request("GET", f"/api/v1/admin/roles/users/{path_arg(user_id)}")

    def set_users(self, user_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/roles/users/{user_id}

        Set User Roles

        Body fields: roles (List[Any])"""
        return self._t.request("PUT", f"/api/v1/admin/roles/users/{path_arg(user_id)}", json=body)

    def get_me_admin_access(self) -> Any:
        """GET /api/v1/me/admin-access

        My Access

        What the signed-in administrator can do, so the UI can hide what would only be refused.

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/admin-access")

class _Administrators:
    """Endpoints in the `administrators` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self, *, role: Optional[str] = None, mfa: Optional[str] = None, q: Optional[str] = None, start_index: Optional[int] = None, count: Optional[int] = None, sort_by: Optional[str] = None, sort_order: Optional[str] = None, filter: Optional[str] = None) -> Any:
        """GET /api/v1/admin/administrators

        List Administrators"""
        return self._t.request("GET", "/api/v1/admin/administrators", query={"role": role, "mfa": mfa, "q": q, "startIndex": start_index, "count": count, "sortBy": sort_by, "sortOrder": sort_order, "filter": filter})

class _ApiTokens:
    """Endpoints in the `api_tokens` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self, *, all: Optional[bool] = None) -> Any:
        """GET /api/v1/admin/api-tokens

        List Tokens"""
        return self._t.request("GET", "/api/v1/admin/api-tokens", query={"all": all})

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/api-tokens

        Create Token

        Body fields: name (str, required), password (str, required), expires_in_days (int), read_only (bool), allowed_cidrs (List[Any])"""
        return self._t.request("POST", "/api/v1/admin/api-tokens", json=body)

    def delete(self, token_id: int) -> Any:
        """DELETE /api/v1/admin/api-tokens/{token_id}

        Revoke Token"""
        return self._t.request("DELETE", f"/api/v1/admin/api-tokens/{path_arg(token_id)}")

class _Applications:
    """Endpoints in the `applications` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self, *, q: Optional[str] = None, owner_user_id: Optional[int] = None, sensitivity: Optional[str] = None, tag: Optional[str] = None) -> Any:
        """GET /api/v1/admin/applications

        List Applications"""
        return self._t.request("GET", "/api/v1/admin/applications", query={"q": q, "owner_user_id": owner_user_id, "sensitivity": sensitivity, "tag": tag})

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/applications

        Create Application

        Body fields: name (str, required), description (str), sign_on_mode (str), launch_url (str), status (str), visible (bool), require_assignment (bool), owner_user_id (int), sensitivity (str), review_by (str), tags (List[Any]), attributes (Dict[str, Any])"""
        return self._t.request("POST", "/api/v1/admin/applications", json=body)

    def from_template(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/applications/from-template

        From Template

        An application and its OIDC client in one transaction; the client secret (if any) is returned once.

        Body fields: template (str, required), name (str, required), description (str), redirect_uris (List[Any]), post_logout_redirect_uris (List[Any]), launch_url (str), initiate_login_uri (str), require_assignment (bool), allowed_scopes (List[Any]), allowed_audiences (List[Any])"""
        return self._t.request("POST", "/api/v1/admin/applications/from-template", json=body)

    def get_templates(self) -> Any:
        """GET /api/v1/admin/applications/templates

        Templates"""
        return self._t.request("GET", "/api/v1/admin/applications/templates")

    def delete(self, app_id: int) -> Any:
        """DELETE /api/v1/admin/applications/{app_id}

        Delete Application"""
        return self._t.request("DELETE", f"/api/v1/admin/applications/{path_arg(app_id)}")

    def get(self, app_id: int) -> Any:
        """GET /api/v1/admin/applications/{app_id}

        Get Application"""
        return self._t.request("GET", f"/api/v1/admin/applications/{path_arg(app_id)}")

    def replace(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/applications/{app_id}

        Update Application

        Body fields: name (str, required), description (str), sign_on_mode (str), launch_url (str), status (str), visible (bool), require_assignment (bool), owner_user_id (int), sensitivity (str), review_by (str), tags (List[Any]), attributes (Dict[str, Any])"""
        return self._t.request("PUT", f"/api/v1/admin/applications/{path_arg(app_id)}", json=body)

    def get_assignments(self, app_id: int) -> Any:
        """GET /api/v1/admin/applications/{app_id}/assignments

        List Assignments"""
        return self._t.request("GET", f"/api/v1/admin/applications/{path_arg(app_id)}/assignments")

    def assignments(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/applications/{app_id}/assignments

        Add Assignment

        Body fields: user_id (int), group_id (int)"""
        return self._t.request("POST", f"/api/v1/admin/applications/{path_arg(app_id)}/assignments", json=body)

    def delete_assignments(self, app_id: int, assignment_id: int) -> Any:
        """DELETE /api/v1/admin/applications/{app_id}/assignments/{assignment_id}

        Remove Assignment"""
        return self._t.request("DELETE", f"/api/v1/admin/applications/{path_arg(app_id)}/assignments/{path_arg(assignment_id)}")

    def delete_icon(self, app_id: int) -> Any:
        """DELETE /api/v1/admin/applications/{app_id}/icon

        Remove Icon"""
        return self._t.request("DELETE", f"/api/v1/admin/applications/{path_arg(app_id)}/icon")

    def get_icon(self, app_id: int) -> Any:
        """GET /api/v1/admin/applications/{app_id}/icon

        Get Icon"""
        return self._t.request("GET", f"/api/v1/admin/applications/{path_arg(app_id)}/icon")

    def set_icon(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/applications/{app_id}/icon

        Set Icon

        Body fields: data (str, required)"""
        return self._t.request("PUT", f"/api/v1/admin/applications/{path_arg(app_id)}/icon", json=body)

    def delete_oidc_client(self, app_id: int) -> Any:
        """DELETE /api/v1/admin/applications/{app_id}/oidc-client

        Detach Oidc Client"""
        return self._t.request("DELETE", f"/api/v1/admin/applications/{path_arg(app_id)}/oidc-client")

    def oidc_client(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/applications/{app_id}/oidc-client

        Attach Oidc Client

        Body fields: client_pk (int, required)"""
        return self._t.request("POST", f"/api/v1/admin/applications/{path_arg(app_id)}/oidc-client", json=body)

    def get_me_apps(self) -> Any:
        """GET /api/v1/me/apps

        My Apps

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/apps")

    def get_me_apps_icon(self, app_id: int) -> Any:
        """GET /api/v1/me/apps/{app_id}/icon

        My App Icon

        Needs a session: call client.login() first."""
        return self._t.request("GET", f"/api/v1/me/apps/{path_arg(app_id)}/icon")

    def me_apps_launch(self, app_id: int) -> Any:
        """POST /api/v1/me/apps/{app_id}/launch

        Launch

        Needs a session: call client.login() first."""
        return self._t.request("POST", f"/api/v1/me/apps/{path_arg(app_id)}/launch")

class _Audit:
    """Endpoints in the `audit` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self, *, action: Optional[str] = None, actor_id: Optional[int] = None, target_type: Optional[str] = None, target_id: Optional[str] = None, q: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None, start_index: Optional[int] = None, count: Optional[int] = None, sort_by: Optional[str] = None, sort_order: Optional[str] = None, filter: Optional[str] = None) -> Any:
        """GET /api/v1/admin/audit

        List Audit"""
        return self._t.request("GET", "/api/v1/admin/audit", query={"action": action, "actor_id": actor_id, "target_type": target_type, "target_id": target_id, "q": q, "since": since, "until": until, "startIndex": start_index, "count": count, "sortBy": sort_by, "sortOrder": sort_order, "filter": filter})

    def get_actions(self) -> Any:
        """GET /api/v1/admin/audit/actions

        Audit Actions"""
        return self._t.request("GET", "/api/v1/admin/audit/actions")

    def get_export(self, *, action: Optional[str] = None, actor_id: Optional[int] = None, target_type: Optional[str] = None, target_id: Optional[str] = None, q: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None) -> Any:
        """GET /api/v1/admin/audit/export

        Export Audit

        CSV of the filtered events (newest first, at most 10,000). The export itself is audited."""
        return self._t.request("GET", "/api/v1/admin/audit/export", query={"action": action, "actor_id": actor_id, "target_type": target_type, "target_id": target_id, "q": q, "since": since, "until": until})

    def get_stats(self) -> Any:
        """GET /api/v1/admin/stats

        Stats"""
        return self._t.request("GET", "/api/v1/admin/stats")

class _Bootstrap:
    """Endpoints in the `bootstrap` section."""

    def __init__(self, t: Transport):
        self._t = t

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/bootstrap

        Bootstrap Admin Endpoint

        Bootstrap first administrator account.

        Body fields: email (str, required), password (str, required), first_name (str, required), last_name (str, required), secret_key (str, required)"""
        return self._t.request("POST", "/api/v1/admin/bootstrap", json=body)

class _Branding:
    """Endpoints in the `branding` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/admin/branding

        Get Branding"""
        return self._t.request("GET", "/api/v1/admin/branding")

    def replace(self, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/branding

        Put Branding

        Body fields: display_name (str), primary_color (str), tagline (str)"""
        return self._t.request("PUT", "/api/v1/admin/branding", json=body)

    def delete_logo(self) -> Any:
        """DELETE /api/v1/admin/branding/logo

        Delete Logo"""
        return self._t.request("DELETE", "/api/v1/admin/branding/logo")

    def set_logo(self, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/branding/logo

        Put Logo

        Body fields: data (str, required)"""
        return self._t.request("PUT", "/api/v1/admin/branding/logo", json=body)

    def get_email_templates(self) -> Any:
        """GET /api/v1/admin/email-templates

        List Templates"""
        return self._t.request("GET", "/api/v1/admin/email-templates")

    def delete_email_templates(self, key: str) -> Any:
        """DELETE /api/v1/admin/email-templates/{key}

        Reset Template"""
        return self._t.request("DELETE", f"/api/v1/admin/email-templates/{path_arg(key)}")

    def set_email_templates(self, key: str, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/email-templates/{key}

        Put Template

        Body fields: subject (str, required), body (str, required)"""
        return self._t.request("PUT", f"/api/v1/admin/email-templates/{path_arg(key)}", json=body)

    def email_templates_preview(self, key: str, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/email-templates/{key}/preview

        Preview Template

        Body fields: subject (str, required), body (str, required)"""
        return self._t.request("POST", f"/api/v1/admin/email-templates/{path_arg(key)}/preview", json=body)

    def email_templates_send_test(self, key: str, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/email-templates/{key}/send-test

        Send Test

        Sends the draft to the signed-in administrator's own address only, so this can never be used to mail anyone else.

        Body fields: subject (str, required), body (str, required)"""
        return self._t.request("POST", f"/api/v1/admin/email-templates/{path_arg(key)}/send-test", json=body)

    def list_get(self) -> Any:
        """GET /api/v1/branding

        Public Branding

        Everything here is already visible to anyone who opens the sign-in page. No secrets, no user data.

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/branding")

    def get_logo(self) -> Any:
        """GET /api/v1/branding/logo

        Public Logo

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/branding/logo")

class _Connectors:
    """Endpoints in the `connectors` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/admin/connectors

        Catalog"""
        return self._t.request("GET", "/api/v1/admin/connectors")

    def get(self, connector_id: str) -> Any:
        """GET /api/v1/admin/connectors/{connector_id}

        One"""
        return self._t.request("GET", f"/api/v1/admin/connectors/{path_arg(connector_id)}")

    def connections(self, connector_id: str, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/connectors/{connector_id}/connections

        Create Connection

        Body fields: name (str, required), config (Dict[str, Any]), secrets (Dict[str, Any]), allowed_users (List[Any])"""
        return self._t.request("POST", f"/api/v1/admin/connectors/{path_arg(connector_id)}/connections", json=body)

    def set_connections(self, connector_id: str, cid: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/connectors/{connector_id}/connections/{cid}

        Update Connection

        Change a connector connection. Leave a secret field out to keep the stored value; send it to rotate it.

        Body fields: name (str, required), config (Dict[str, Any]), secrets (Dict[str, Any]), allowed_users (List[Any])"""
        return self._t.request("PUT", f"/api/v1/admin/connectors/{path_arg(connector_id)}/connections/{path_arg(cid)}", json=body)

    def recipe_connections_test(self, cid: int) -> Any:
        """POST /api/v1/admin/recipe-connections/{cid}/test

        Test Connection

        Run the connector's test request with the stored credentials. Always answers 200 with {ok, message}; the audit log records the attempt."""
        return self._t.request("POST", f"/api/v1/admin/recipe-connections/{path_arg(cid)}/test")

class _Dashboard:
    """Endpoints in the `dashboard` section."""

    def __init__(self, t: Transport):
        self._t = t

    def get_dashboard(self) -> Any:
        """GET /api/v1/admin/dashboard

        Dashboard"""
        return self._t.request("GET", "/api/v1/admin/dashboard")

    def get_dashboard_me(self) -> Any:
        """GET /api/v1/me/dashboard

        Overview

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/dashboard")

    def get_dashboard_activity(self) -> Any:
        """GET /api/v1/me/dashboard/activity

        Activity

        The signed-in user's own security-relevant events. Never other people's, never admin actions on others.

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/dashboard/activity")

    def set_dashboard_apps(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/me/dashboard/apps/{app_id}

        Set App

        Body fields: favorite (bool), section_id (int), clear_section (bool), move (str)

        Needs a session: call client.login() first."""
        return self._t.request("PUT", f"/api/v1/me/dashboard/apps/{path_arg(app_id)}", json=body)

    def dashboard_import_favorites(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/dashboard/import-favorites

        Import Favorites

        One-time move of the old browser-only pins; ids the user cannot see are skipped.

        Body fields: app_ids (List[Any])

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/dashboard/import-favorites", json=body)

    def dashboard_sections(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/dashboard/sections

        Create Section

        Body fields: name (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/dashboard/sections", json=body)

    def delete_dashboard_sections(self, section_id: int) -> Any:
        """DELETE /api/v1/me/dashboard/sections/{section_id}

        Delete Section

        Needs a session: call client.login() first."""
        return self._t.request("DELETE", f"/api/v1/me/dashboard/sections/{path_arg(section_id)}")

    def update_dashboard_sections(self, section_id: int, body: Mapping[str, Any]) -> Any:
        """PATCH /api/v1/me/dashboard/sections/{section_id}

        Update Section

        Body fields: name (str), move (str)

        Needs a session: call client.login() first."""
        return self._t.request("PATCH", f"/api/v1/me/dashboard/sections/{path_arg(section_id)}", json=body)

class _Features:
    """Endpoints in the `features` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/admin/features

        Features"""
        return self._t.request("GET", "/api/v1/admin/features")

class _GroupRules:
    """Endpoints in the `group_rules` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/admin/group-rules

        List Rules"""
        return self._t.request("GET", "/api/v1/admin/group-rules")

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/group-rules

        Create Rule

        Body fields: name (str, required), kind (str), match (str), conditions (List[Any]), expression (str), group_ids (List[Any], required)"""
        return self._t.request("POST", "/api/v1/admin/group-rules", json=body)

    def get_export(self) -> Any:
        """GET /api/v1/admin/group-rules/export

        Export Rules"""
        return self._t.request("GET", "/api/v1/admin/group-rules/export")

    def get_expression_help(self) -> Any:
        """GET /api/v1/admin/group-rules/expression-help

        Expression Help

        Everything the expression editor suggests: functions, operators, and the attributes a rule may read (never the ones users edit themselves)."""
        return self._t.request("GET", "/api/v1/admin/group-rules/expression-help")

    def import_(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/group-rules/import

        Import Rules

        Create rules from a template/export file. Everything is validated first; nothing is created if any rule is invalid (all-or-nothing). Rules arrive INACTIVE, so importing never changes anyone's membership.

        Body fields: document (Dict[str, Any], required), create_missing_groups (bool), dry_run (bool)"""
        return self._t.request("POST", "/api/v1/admin/group-rules/import", json=body)

    def preview(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/group-rules/preview

        Preview

        Body fields: kind (str), match (str), conditions (List[Any]), expression (str)"""
        return self._t.request("POST", "/api/v1/admin/group-rules/preview", json=body)

    def get_template(self) -> Any:
        """GET /api/v1/admin/group-rules/template

        Download Template"""
        return self._t.request("GET", "/api/v1/admin/group-rules/template")

    def validate_expression(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/group-rules/validate-expression

        Validate Expression

        Live check for the editor: does it parse, is it true/false, does it only read attributes a rule may read?

        Body fields: expression (str)"""
        return self._t.request("POST", "/api/v1/admin/group-rules/validate-expression", json=body)

    def delete(self, rule_id: int) -> Any:
        """DELETE /api/v1/admin/group-rules/{rule_id}

        Delete Rule"""
        return self._t.request("DELETE", f"/api/v1/admin/group-rules/{path_arg(rule_id)}")

    def get(self, rule_id: int) -> Any:
        """GET /api/v1/admin/group-rules/{rule_id}

        Get Rule"""
        return self._t.request("GET", f"/api/v1/admin/group-rules/{path_arg(rule_id)}")

    def replace(self, rule_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/group-rules/{rule_id}

        Update Rule

        Body fields: name (str, required), kind (str), match (str), conditions (List[Any]), expression (str), group_ids (List[Any], required)"""
        return self._t.request("PUT", f"/api/v1/admin/group-rules/{path_arg(rule_id)}", json=body)

    def activate(self, rule_id: int) -> Any:
        """POST /api/v1/admin/group-rules/{rule_id}/activate

        Activate"""
        return self._t.request("POST", f"/api/v1/admin/group-rules/{path_arg(rule_id)}/activate")

    def deactivate(self, rule_id: int) -> Any:
        """POST /api/v1/admin/group-rules/{rule_id}/deactivate

        Deactivate"""
        return self._t.request("POST", f"/api/v1/admin/group-rules/{path_arg(rule_id)}/deactivate")

class _Groups:
    """Endpoints in the `groups` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self, *, type: Optional[str] = None, owner_user_id: Optional[int] = None, ownerless: Optional[bool] = None, sensitivity: Optional[str] = None, tag: Optional[str] = None, q: Optional[str] = None, start_index: Optional[int] = None, count: Optional[int] = None, sort_by: Optional[str] = None, sort_order: Optional[str] = None, filter: Optional[str] = None) -> Any:
        """GET /api/v1/admin/groups

        List Groups"""
        return self._t.request("GET", "/api/v1/admin/groups", query={"type": type, "owner_user_id": owner_user_id, "ownerless": ownerless, "sensitivity": sensitivity, "tag": tag, "q": q, "startIndex": start_index, "count": count, "sortBy": sort_by, "sortOrder": sort_order, "filter": filter})

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/groups

        Create Group

        Body fields: name (str, required), description (str), type (str), owner_user_id (int), sensitivity (str), review_by (str), tags (List[Any]), attributes (Dict[str, Any])"""
        return self._t.request("POST", "/api/v1/admin/groups", json=body)

    def get_analytics(self) -> Any:
        """GET /api/v1/admin/groups/analytics

        Group Analytics

        Directory-wide group health: composition by type, ownership gaps, empty and overdue groups."""
        return self._t.request("GET", "/api/v1/admin/groups/analytics")

    def get_standards(self) -> Any:
        """GET /api/v1/admin/groups/standards

        Group Standards

        The group types and metadata rules, in a form scripts and AI assistants can read."""
        return self._t.request("GET", "/api/v1/admin/groups/standards")

    def delete(self, group_id: int) -> Any:
        """DELETE /api/v1/admin/groups/{group_id}

        Delete Group"""
        return self._t.request("DELETE", f"/api/v1/admin/groups/{path_arg(group_id)}")

    def get(self, group_id: int) -> Any:
        """GET /api/v1/admin/groups/{group_id}

        Get Group"""
        return self._t.request("GET", f"/api/v1/admin/groups/{path_arg(group_id)}")

    def update(self, group_id: int, body: Mapping[str, Any]) -> Any:
        """PATCH /api/v1/admin/groups/{group_id}

        Update Group

        Body fields: name (str), description (str), type (str), owner_user_id (int), sensitivity (str), review_by (str), tags (List[Any]), attributes (Dict[str, Any])"""
        return self._t.request("PATCH", f"/api/v1/admin/groups/{path_arg(group_id)}", json=body)

    def members(self, group_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/groups/{group_id}/members

        Add Member

        Body fields: user_id (int, required)"""
        return self._t.request("POST", f"/api/v1/admin/groups/{path_arg(group_id)}/members", json=body)

    def delete_members(self, group_id: int, user_id: int) -> Any:
        """DELETE /api/v1/admin/groups/{group_id}/members/{user_id}

        Remove Member"""
        return self._t.request("DELETE", f"/api/v1/admin/groups/{path_arg(group_id)}/members/{path_arg(user_id)}")

class _Login:
    """Endpoints in the `login_` section."""

    def __init__(self, t: Transport):
        self._t = t

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/login

        Login Endpoint

        Authenticate user, create a session and set the session cookie.

        Body fields: email (str, required), password (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/login", json=body)

class _Logout:
    """Endpoints in the `logout` section."""

    def __init__(self, t: Transport):
        self._t = t

    def create(self) -> Any:
        """POST /api/v1/logout

        Logout Endpoint

        Revoke the server-side session and clear the cookie (CSRF-protected).

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/logout")

class _LookupTables:
    """Endpoints in the `lookup_tables` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/admin/lookup-tables

        List Tables"""
        return self._t.request("GET", "/api/v1/admin/lookup-tables")

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/lookup-tables

        Create Table

        Body fields: name (str, required), description (str), columns (List[Any], required), key_column (str), admin_managed (bool)"""
        return self._t.request("POST", "/api/v1/admin/lookup-tables", json=body)

    def delete(self, tid: int) -> Any:
        """DELETE /api/v1/admin/lookup-tables/{tid}

        Delete Table"""
        return self._t.request("DELETE", f"/api/v1/admin/lookup-tables/{path_arg(tid)}")

    def get(self, tid: int) -> Any:
        """GET /api/v1/admin/lookup-tables/{tid}

        Get Table"""
        return self._t.request("GET", f"/api/v1/admin/lookup-tables/{path_arg(tid)}")

    def replace(self, tid: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/lookup-tables/{tid}

        Update Table

        Body fields: description (str), admin_managed (bool), add_columns (List[Any])"""
        return self._t.request("PUT", f"/api/v1/admin/lookup-tables/{path_arg(tid)}", json=body)

    def get_export(self, tid: int) -> Any:
        """GET /api/v1/admin/lookup-tables/{tid}/export

        Export Rows"""
        return self._t.request("GET", f"/api/v1/admin/lookup-tables/{path_arg(tid)}/export")

    def import_(self, tid: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/lookup-tables/{tid}/import

        Import Rows

        All or nothing: the first problems are listed with their line numbers and nothing is written.

        Body fields: csv (str, required), mode (str)"""
        return self._t.request("POST", f"/api/v1/admin/lookup-tables/{path_arg(tid)}/import", json=body)

    def get_rows(self, tid: int, *, q: Optional[str] = None, start_index: Optional[int] = None, count: Optional[int] = None, sort_by: Optional[str] = None, sort_order: Optional[str] = None, filter: Optional[str] = None) -> Any:
        """GET /api/v1/admin/lookup-tables/{tid}/rows

        List Rows"""
        return self._t.request("GET", f"/api/v1/admin/lookup-tables/{path_arg(tid)}/rows", query={"q": q, "startIndex": start_index, "count": count, "sortBy": sort_by, "sortOrder": sort_order, "filter": filter})

    def rows(self, tid: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/lookup-tables/{tid}/rows

        Add Row

        Body fields: values (Dict[str, Any], required)"""
        return self._t.request("POST", f"/api/v1/admin/lookup-tables/{path_arg(tid)}/rows", json=body)

    def delete_rows(self, tid: int, rid: int) -> Any:
        """DELETE /api/v1/admin/lookup-tables/{tid}/rows/{rid}

        Delete Row"""
        return self._t.request("DELETE", f"/api/v1/admin/lookup-tables/{path_arg(tid)}/rows/{path_arg(rid)}")

    def set_rows(self, tid: int, rid: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/lookup-tables/{tid}/rows/{rid}

        Update Row

        Body fields: values (Dict[str, Any], required)"""
        return self._t.request("PUT", f"/api/v1/admin/lookup-tables/{path_arg(tid)}/rows/{path_arg(rid)}", json=body)

class _Me:
    """Endpoints in the `me` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/me

        Get Current User Endpoint

        Return the authenticated user plus the CSRF token for this session.

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me")

class _Mfa:
    """Endpoints in the `mfa` section."""

    def __init__(self, t: Transport):
        self._t = t

    def users_enrollment_code(self, user_id: int) -> Any:
        """POST /api/v1/admin/users/{user_id}/enrollment-code

        Issue Enrollment Code

        A super admin hands an admin the one-time code they need to enrol their first factor. A super admin's own code comes from the operator CLI (nobody above them)."""
        return self._t.request("POST", f"/api/v1/admin/users/{path_arg(user_id)}/enrollment-code")

    def users_mfa_reset(self, user_id: int) -> Any:
        """POST /api/v1/admin/users/{user_id}/mfa/reset

        Admin Reset Mfa

        Remove all of a user's extra sign-in factors: TOTP, recovery codes and passkeys, and lift the passkey-required policy (lost device). Same target protections as other admin actions."""
        return self._t.request("POST", f"/api/v1/admin/users/{path_arg(user_id)}/mfa/reset")

    def login_mfa(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/login/mfa

        Login Mfa

        Exchange (challenge token + TOTP/recovery code) for a session.

        Body fields: mfa_token (str, required), code (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/login/mfa", json=body)

    def get_mfa(self) -> Any:
        """GET /api/v1/me/mfa

        Mfa Status

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/mfa")

    def mfa_disable(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/mfa/disable

        Mfa Disable

        Body fields: password (str, required), code (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/mfa/disable", json=body)

    def mfa_enable(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/mfa/enable

        Mfa Enable

        Confirm enrolment with a code from the authenticator app; returns recovery codes once.

        Body fields: code (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/mfa/enable", json=body)

    def mfa_recovery_codes(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/mfa/recovery-codes

        Mfa Regenerate

        Body fields: password (str, required), code (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/mfa/recovery-codes", json=body)

    def mfa_setup(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/mfa/setup

        Mfa Setup

        Start enrolment (requires the current password, plus an enrolment code for admins with no factor yet). Replaces any unconfirmed attempt.

        Body fields: password (str, required), enrollment_code (str)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/mfa/setup", json=body)

class _Oidc:
    """Endpoints in the `oidc` section."""

    def __init__(self, t: Transport):
        self._t = t

    def get_well_known_openid_configuration(self, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """GET /.well-known/openid-configuration

        Discovery

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("GET", "/.well-known/openid-configuration", query=query)

    def get_me_consents(self) -> Any:
        """GET /api/v1/me/consents

        List Consents

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/consents")

    def delete_me_consents(self, client_pk: int) -> Any:
        """DELETE /api/v1/me/consents/{client_pk}

        Withdraw

        Needs a session: call client.login() first."""
        return self._t.request("DELETE", f"/api/v1/me/consents/{path_arg(client_pk)}")

    def get_oidc_authorization_requests(self, request_id: str) -> Any:
        """GET /api/v1/oidc/authorization-requests/{request_id}

        Get Request

        Needs a session: call client.login() first."""
        return self._t.request("GET", f"/api/v1/oidc/authorization-requests/{path_arg(request_id)}")

    def oidc_authorization_requests_decision(self, request_id: str, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/oidc/authorization-requests/{request_id}/decision

        Decide

        Body fields: approve (bool, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", f"/api/v1/oidc/authorization-requests/{path_arg(request_id)}/decision", json=body)

    def oidc_logout(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/oidc/logout

        Logout

        Body fields: id_token_hint (str), post_logout_redirect_uri (str), state (str), client_id (str)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/oidc/logout", json=body)

    def get_oidc_logout_request(self) -> Any:
        """GET /api/v1/oidc/logout-request

        Logout Request

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/oidc/logout-request")

    def get_authorize(self, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """GET /oauth/authorize

        Authorize

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("GET", "/oauth/authorize", query=query)

    def introspect(self, form: Optional[Mapping[str, Any]] = None, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """POST /oauth/introspect

        Introspect

        RFC 7662. Only confidential/service clients, authenticated with their secret.

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("POST", "/oauth/introspect", query=query, form=form)

    def get_jwks(self, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """GET /oauth/jwks

        Jwks

        Public signing keys. Unauthenticated, credential-free CORS (any origin may read public keys).

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("GET", "/oauth/jwks", query=query)

    def get_logout(self, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """GET /oauth/logout

        Logout Entry

        Hand the browser to the confirmation page with only the parameters we understand.

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("GET", "/oauth/logout", query=query)

    def logout(self, form: Optional[Mapping[str, Any]] = None, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """POST /oauth/logout

        Logout Entry

        Hand the browser to the confirmation page with only the parameters we understand.

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("POST", "/oauth/logout", query=query, form=form)

    def revoke(self, form: Optional[Mapping[str, Any]] = None, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """POST /oauth/revoke

        Revoke

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("POST", "/oauth/revoke", query=query, form=form)

    def token_post(self, form: Optional[Mapping[str, Any]] = None, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """POST /oauth/token

        Token

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("POST", "/oauth/token", query=query, form=form)

    def get_userinfo(self, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """GET /oauth/userinfo

        Userinfo

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("GET", "/oauth/userinfo", query=query)

    def userinfo(self, form: Optional[Mapping[str, Any]] = None, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """POST /oauth/userinfo

        Userinfo

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("POST", "/oauth/userinfo", query=query, form=form)

class _OidcAdmin:
    """Endpoints in the `oidc_admin` section."""

    def __init__(self, t: Transport):
        self._t = t

    def get_keys(self) -> Any:
        """GET /api/v1/admin/oidc/keys

        List Keys"""
        return self._t.request("GET", "/api/v1/admin/oidc/keys")

    def keys_rotate(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/oidc/keys/rotate

        Rotate Key

        Body fields: emergency (bool), alg (str), confirm (bool)"""
        return self._t.request("POST", "/api/v1/admin/oidc/keys/rotate", json=body)

class _OidcClients:
    """Endpoints in the `oidc_clients` section."""

    def __init__(self, t: Transport):
        self._t = t

    def get_clients(self) -> Any:
        """GET /api/v1/admin/oidc/clients

        List Clients"""
        return self._t.request("GET", "/api/v1/admin/oidc/clients")

    def clients(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/oidc/clients

        Create Client

        Body fields: name (str, required), description (str), client_type (str), redirect_uris (List[Any]), post_logout_redirect_uris (List[Any]), allowed_scopes (List[Any]), allowed_audiences (List[Any]), token_endpoint_auth_method (str), jwks (Dict[str, Any]), first_party (bool), initiate_login_uri (str), launch_url (str), require_assignment (bool), application_id (int), access_token_format (str)"""
        return self._t.request("POST", "/api/v1/admin/oidc/clients", json=body)

    def delete_clients(self, pk: int) -> Any:
        """DELETE /api/v1/admin/oidc/clients/{pk}

        Delete Client"""
        return self._t.request("DELETE", f"/api/v1/admin/oidc/clients/{path_arg(pk)}")

    def get_clients_by_pk(self, pk: int) -> Any:
        """GET /api/v1/admin/oidc/clients/{pk}

        Get Client"""
        return self._t.request("GET", f"/api/v1/admin/oidc/clients/{path_arg(pk)}")

    def update_clients(self, pk: int, body: Mapping[str, Any]) -> Any:
        """PATCH /api/v1/admin/oidc/clients/{pk}

        Update Client

        Body fields: name (str), description (str), redirect_uris (List[Any]), post_logout_redirect_uris (List[Any]), allowed_scopes (List[Any]), allowed_audiences (List[Any]), jwks (Dict[str, Any]), status (str), first_party (bool), access_token_format (str), initiate_login_uri (str)"""
        return self._t.request("PATCH", f"/api/v1/admin/oidc/clients/{path_arg(pk)}", json=body)

    def clients_secrets(self, pk: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/oidc/clients/{pk}/secrets

        Add Client Secret

        Body fields: expires_in_days (int)"""
        return self._t.request("POST", f"/api/v1/admin/oidc/clients/{path_arg(pk)}/secrets", json=body)

    def delete_clients_secrets(self, pk: int, secret_id: int) -> Any:
        """DELETE /api/v1/admin/oidc/clients/{pk}/secrets/{secret_id}

        Revoke Client Secret"""
        return self._t.request("DELETE", f"/api/v1/admin/oidc/clients/{path_arg(pk)}/secrets/{path_arg(secret_id)}")

class _Passkeys:
    """Endpoints in the `passkeys` section."""

    def __init__(self, t: Transport):
        self._t = t

    def login_passkey_options(self) -> Any:
        """POST /api/v1/login/passkey/options

        Login Options

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/login/passkey/options")

    def login_passkey_verify(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/login/passkey/verify

        Login Verify

        Body fields: ceremony_id (str, required), credential (Dict[str, Any], required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/login/passkey/verify", json=body)

    def get_passkeys(self) -> Any:
        """GET /api/v1/me/passkeys

        List Passkeys

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/passkeys")

    def passkeys_policy(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/passkeys/policy

        Set Policy

        'Require a passkey to sign in': password sign-in is refused for this account.

        Body fields: password (str, required), require (bool, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/passkeys/policy", json=body)

    def passkeys_register_options(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/passkeys/register/options

        Register Options

        Body fields: password (str, required), enrollment_code (str)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/passkeys/register/options", json=body)

    def passkeys_register_verify(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/passkeys/register/verify

        Register Verify

        Body fields: ceremony_id (str, required), credential (Dict[str, Any], required), name (str)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/passkeys/register/verify", json=body)

    def update_passkeys(self, passkey_id: int, body: Mapping[str, Any]) -> Any:
        """PATCH /api/v1/me/passkeys/{passkey_id}

        Rename Passkey

        Body fields: name (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("PATCH", f"/api/v1/me/passkeys/{path_arg(passkey_id)}", json=body)

    def passkeys_remove(self, passkey_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/passkeys/{passkey_id}/remove

        Remove Passkey

        Body fields: password (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", f"/api/v1/me/passkeys/{path_arg(passkey_id)}/remove", json=body)

class _Policies:
    """Endpoints in the `policies` section."""

    def __init__(self, t: Transport):
        self._t = t

    def delete_applications_policy(self, app_id: int) -> Any:
        """DELETE /api/v1/admin/applications/{app_id}/policy

        Delete Policy"""
        return self._t.request("DELETE", f"/api/v1/admin/applications/{path_arg(app_id)}/policy")

    def get_applications_policy(self, app_id: int) -> Any:
        """GET /api/v1/admin/applications/{app_id}/policy

        Get Policy"""
        return self._t.request("GET", f"/api/v1/admin/applications/{path_arg(app_id)}/policy")

    def set_applications_policy(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/applications/{app_id}/policy

        Put Policy

        Body fields: require_mfa (bool), reauth_minutes (int), allowed_zone_ids (List[Any]), blocked_zone_ids (List[Any])"""
        return self._t.request("PUT", f"/api/v1/admin/applications/{path_arg(app_id)}/policy", json=body)

    def list(self) -> Any:
        """GET /api/v1/admin/network-zones

        List Zones"""
        return self._t.request("GET", "/api/v1/admin/network-zones")

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/network-zones

        Create Zone

        Body fields: name (str, required), cidrs (List[Any], required)"""
        return self._t.request("POST", "/api/v1/admin/network-zones", json=body)

    def delete(self, zone_id: int) -> Any:
        """DELETE /api/v1/admin/network-zones/{zone_id}

        Delete Zone"""
        return self._t.request("DELETE", f"/api/v1/admin/network-zones/{path_arg(zone_id)}")

    def replace(self, zone_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/network-zones/{zone_id}

        Update Zone

        Body fields: name (str, required), cidrs (List[Any], required)"""
        return self._t.request("PUT", f"/api/v1/admin/network-zones/{path_arg(zone_id)}", json=body)

class _Profile:
    """Endpoints in the `profile` section."""

    def __init__(self, t: Transport):
        self._t = t

    def get_activity(self, *, limit: Optional[int] = None) -> Any:
        """GET /api/v1/me/activity

        My Activity

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/activity", query={"limit": limit})

    def password(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/password

        Change Password

        Body fields: current_password (str, required), new_password (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/password", json=body)

    def get_profile(self) -> Any:
        """GET /api/v1/me/profile

        Get Profile

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/profile")

    def update_profile(self, body: Mapping[str, Any]) -> Any:
        """PATCH /api/v1/me/profile

        Update Profile

        Body fields: first_name (str), last_name (str), profile_attributes (Dict[str, Any])

        Needs a session: call client.login() first."""
        return self._t.request("PATCH", "/api/v1/me/profile", json=body)

    def get_sessions(self) -> Any:
        """GET /api/v1/me/sessions

        My Sessions

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/me/sessions")

class _ProfileEditor:
    """Endpoints in the `profile_editor` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/admin/profile-attributes

        List Attributes"""
        return self._t.request("GET", "/api/v1/admin/profile-attributes")

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/profile-attributes

        Create Attribute

        Body fields: key (str, required), display_name (str, required), description (str), data_type (str), enum_options (List[Any]), user_editable (bool)"""
        return self._t.request("POST", "/api/v1/admin/profile-attributes", json=body)

    def delete(self, key: str) -> Any:
        """DELETE /api/v1/admin/profile-attributes/{key}

        Delete Attribute"""
        return self._t.request("DELETE", f"/api/v1/admin/profile-attributes/{path_arg(key)}")

    def update(self, key: str, body: Mapping[str, Any]) -> Any:
        """PATCH /api/v1/admin/profile-attributes/{key}

        Update Attribute

        Body fields: display_name (str), description (str), enum_options (List[Any]), user_editable (bool)"""
        return self._t.request("PATCH", f"/api/v1/admin/profile-attributes/{path_arg(key)}", json=body)

class _Provisioning:
    """Endpoints in the `provisioning` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/admin/provisioning-apps

        List Apps"""
        return self._t.request("GET", "/api/v1/admin/provisioning-apps")

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/provisioning-apps

        Create App

        Body fields: name (str, required), description (str), kind (str, required), base_url (str, required), auth_type (str, required), token_url (str), client_id (str), scope (str), header_name (str), secret (str), enabled (bool), options (Dict[str, Any]), mapping (List[Any]), rest_config (Dict[str, Any]), application_id (int)"""
        return self._t.request("POST", "/api/v1/admin/provisioning-apps", json=body)

    def get_mapping(self) -> Any:
        """GET /api/v1/admin/provisioning-apps/mapping

        Mapping Info"""
        return self._t.request("GET", "/api/v1/admin/provisioning-apps/mapping")

    def get_presets(self) -> Any:
        """GET /api/v1/admin/provisioning-apps/presets

        Presets"""
        return self._t.request("GET", "/api/v1/admin/provisioning-apps/presets")

    def delete(self, app_id: int) -> Any:
        """DELETE /api/v1/admin/provisioning-apps/{app_id}

        Delete App"""
        return self._t.request("DELETE", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}")

    def get(self, app_id: int) -> Any:
        """GET /api/v1/admin/provisioning-apps/{app_id}

        Get App"""
        return self._t.request("GET", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}")

    def replace(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/provisioning-apps/{app_id}

        Update App

        Body fields: name (str, required), description (str), kind (str, required), base_url (str, required), auth_type (str, required), token_url (str), client_id (str), scope (str), header_name (str), secret (str), enabled (bool), options (Dict[str, Any]), mapping (List[Any]), rest_config (Dict[str, Any]), application_id (int)"""
        return self._t.request("PUT", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}", json=body)

    def get_assignments(self, app_id: int) -> Any:
        """GET /api/v1/admin/provisioning-apps/{app_id}/assignments

        List Assignments"""
        return self._t.request("GET", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/assignments")

    def assignments(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/provisioning-apps/{app_id}/assignments

        Add Assignment

        Body fields: user_id (int), group_id (int)"""
        return self._t.request("POST", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/assignments", json=body)

    def delete_assignments(self, app_id: int, assignment_id: int) -> Any:
        """DELETE /api/v1/admin/provisioning-apps/{app_id}/assignments/{assignment_id}

        Remove Assignment"""
        return self._t.request("DELETE", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/assignments/{path_arg(assignment_id)}")

    def deprovision_all(self, app_id: int) -> Any:
        """POST /api/v1/admin/provisioning-apps/{app_id}/deprovision-all

        Deprovision All

        Remove every assignment and queue the work: each provisioned account is deactivated/deleted per the app's policy. Keep the app turned on until the queue is empty; delete it afterwards."""
        return self._t.request("POST", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/deprovision-all")

    def get_links(self, app_id: int, *, state: Optional[str] = None, q: Optional[str] = None, start_index: Optional[int] = None, count: Optional[int] = None, sort_by: Optional[str] = None, sort_order: Optional[str] = None, filter: Optional[str] = None) -> Any:
        """GET /api/v1/admin/provisioning-apps/{app_id}/links

        List Links"""
        return self._t.request("GET", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/links", query={"state": state, "q": q, "startIndex": start_index, "count": count, "sortBy": sort_by, "sortOrder": sort_order, "filter": filter})

    def get_preview(self, app_id: int, *, user_id: int) -> Any:
        """GET /api/v1/admin/provisioning-apps/{app_id}/preview

        Preview

        What would be sent for this user (the canonical SCIM resource; a gateway maps it into the app's own JSON)."""
        return self._t.request("GET", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/preview", query={"user_id": user_id})

    def sync(self, app_id: int) -> Any:
        """POST /api/v1/admin/provisioning-apps/{app_id}/sync

        Sync App"""
        return self._t.request("POST", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/sync")

    def get_tasks(self, app_id: int, *, status: Optional[str] = None) -> Any:
        """GET /api/v1/admin/provisioning-apps/{app_id}/tasks

        List Tasks"""
        return self._t.request("GET", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/tasks", query={"status": status})

    def tasks_retry(self, app_id: int, task_id: int) -> Any:
        """POST /api/v1/admin/provisioning-apps/{app_id}/tasks/{task_id}/retry

        Retry Task"""
        return self._t.request("POST", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/tasks/{path_arg(task_id)}/retry")

    def test(self, app_id: int) -> Any:
        """POST /api/v1/admin/provisioning-apps/{app_id}/test

        Test App"""
        return self._t.request("POST", f"/api/v1/admin/provisioning-apps/{path_arg(app_id)}/test")

class _Recipes:
    """Endpoints in the `recipes` section."""

    def __init__(self, t: Transport):
        self._t = t

    def get_recipe_connections(self) -> Any:
        """GET /api/v1/admin/recipe-connections

        List Connections"""
        return self._t.request("GET", "/api/v1/admin/recipe-connections")

    def recipe_connections(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/recipe-connections

        Create Connection

        Body fields: name (str, required), kind (str, required), header_name (str), allowed_host (str), allowed_paths (List[Any]), client_id (str), token_url (str), scope (str), secret (str), allowed_users (List[Any])"""
        return self._t.request("POST", "/api/v1/admin/recipe-connections", json=body)

    def delete_recipe_connections(self, cid: int) -> Any:
        """DELETE /api/v1/admin/recipe-connections/{cid}

        Delete Connection"""
        return self._t.request("DELETE", f"/api/v1/admin/recipe-connections/{path_arg(cid)}")

    def set_recipe_connections(self, cid: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/recipe-connections/{cid}

        Update Connection

        Body fields: name (str, required), kind (str, required), header_name (str), allowed_host (str), allowed_paths (List[Any]), client_id (str), token_url (str), scope (str), secret (str), allowed_users (List[Any])"""
        return self._t.request("PUT", f"/api/v1/admin/recipe-connections/{path_arg(cid)}", json=body)

    def list(self) -> Any:
        """GET /api/v1/admin/recipes

        List Recipes"""
        return self._t.request("GET", "/api/v1/admin/recipes")

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/recipes

        Create Recipe

        Body fields: name (str, required), description (str), definition (Dict[str, Any])"""
        return self._t.request("POST", "/api/v1/admin/recipes", json=body)

    def from_template(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/recipes/from-template

        From Template

        Body fields: template_id (str, required), name (str, required), params (Dict[str, Any])"""
        return self._t.request("POST", "/api/v1/admin/recipes/from-template", json=body)

    def import_(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/recipes/import

        Import Recipe

        Body fields: document (Dict[str, Any], required), name (str)"""
        return self._t.request("POST", "/api/v1/admin/recipes/import", json=body)

    def get_jobs(self, *, recipe_id: Optional[int] = None, status: Optional[str] = None, start_index: Optional[int] = None, count: Optional[int] = None, sort_by: Optional[str] = None, sort_order: Optional[str] = None, filter: Optional[str] = None) -> Any:
        """GET /api/v1/admin/recipes/jobs

        List Jobs"""
        return self._t.request("GET", "/api/v1/admin/recipes/jobs", query={"recipe_id": recipe_id, "status": status, "startIndex": start_index, "count": count, "sortBy": sort_by, "sortOrder": sort_order, "filter": filter})

    def get_jobs_by_job_id(self, job_id: int) -> Any:
        """GET /api/v1/admin/recipes/jobs/{job_id}

        Get Job"""
        return self._t.request("GET", f"/api/v1/admin/recipes/jobs/{path_arg(job_id)}")

    def jobs_approve(self, job_id: int) -> Any:
        """POST /api/v1/admin/recipes/jobs/{job_id}/approve

        Approve Job"""
        return self._t.request("POST", f"/api/v1/admin/recipes/jobs/{path_arg(job_id)}/approve")

    def jobs_cancel(self, job_id: int) -> Any:
        """POST /api/v1/admin/recipes/jobs/{job_id}/cancel

        Cancel Job

        Queued jobs are cancelled at once; a running job stops before its next step (a step already in flight finishes)."""
        return self._t.request("POST", f"/api/v1/admin/recipes/jobs/{path_arg(job_id)}/cancel")

    def jobs_deny(self, job_id: int) -> Any:
        """POST /api/v1/admin/recipes/jobs/{job_id}/deny

        Deny Job"""
        return self._t.request("POST", f"/api/v1/admin/recipes/jobs/{path_arg(job_id)}/deny")

    def jobs_rerun(self, job_id: int) -> Any:
        """POST /api/v1/admin/recipes/jobs/{job_id}/rerun

        Rerun Job

        Run the same definition and trigger again as a NEW job (Workato-style). At-least-once: effects the first run already had (HTTP calls, group changes that were not idempotent) happen again, so this is an explicit admin action."""
        return self._t.request("POST", f"/api/v1/admin/recipes/jobs/{path_arg(job_id)}/rerun")

    def get_meta(self) -> Any:
        """GET /api/v1/admin/recipes/meta

        Meta"""
        return self._t.request("GET", "/api/v1/admin/recipes/meta")

    def get_metrics(self, *, hours: Optional[int] = None) -> Any:
        """GET /api/v1/admin/recipes/metrics

        Metrics

        Per-recipe health over the last N hours (live jobs only) plus queue depth. Failure rate = failed / finished."""
        return self._t.request("GET", "/api/v1/admin/recipes/metrics", query={"hours": hours})

    def get_status(self) -> Any:
        """GET /api/v1/admin/recipes/status

        Status"""
        return self._t.request("GET", "/api/v1/admin/recipes/status")

    def get_templates(self) -> Any:
        """GET /api/v1/admin/recipes/templates

        List Templates"""
        return self._t.request("GET", "/api/v1/admin/recipes/templates")

    def delete(self, recipe_id: int) -> Any:
        """DELETE /api/v1/admin/recipes/{recipe_id}

        Delete Recipe"""
        return self._t.request("DELETE", f"/api/v1/admin/recipes/{path_arg(recipe_id)}")

    def get(self, recipe_id: int) -> Any:
        """GET /api/v1/admin/recipes/{recipe_id}

        Get Recipe"""
        return self._t.request("GET", f"/api/v1/admin/recipes/{path_arg(recipe_id)}")

    def replace(self, recipe_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/recipes/{recipe_id}

        Update Recipe

        Body fields: name (str, required), description (str), definition (Dict[str, Any])"""
        return self._t.request("PUT", f"/api/v1/admin/recipes/{path_arg(recipe_id)}", json=body)

    def get_callers(self, recipe_id: int) -> Any:
        """GET /api/v1/admin/recipes/{recipe_id}/callers

        Callers

        Recipes that call this one: shown before the callee is changed or published."""
        return self._t.request("GET", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/callers")

    def disable(self, recipe_id: int) -> Any:
        """POST /api/v1/admin/recipes/{recipe_id}/disable

        Disable"""
        return self._t.request("POST", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/disable")

    def enable(self, recipe_id: int) -> Any:
        """POST /api/v1/admin/recipes/{recipe_id}/enable

        Enable"""
        return self._t.request("POST", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/enable")

    def get_export(self, recipe_id: int) -> Any:
        """GET /api/v1/admin/recipes/{recipe_id}/export

        Export Recipe

        The DRAFT as a portable document. No secrets, no ids that only mean something here."""
        return self._t.request("GET", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/export")

    def formula_preview(self, recipe_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/recipes/{recipe_id}/formula-preview

        Formula Preview

        Evaluate fields (pills and formulas) against a sample event. Reads only; earlier steps' outputs are not available.

        Body fields: user_id (int), group_id (int), payload (Dict[str, Any]), templates (List[Any])"""
        return self._t.request("POST", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/formula-preview", json=body)

    def publish(self, recipe_id: int) -> Any:
        """POST /api/v1/admin/recipes/{recipe_id}/publish

        Publish"""
        return self._t.request("POST", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/publish")

    def run(self, recipe_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/recipes/{recipe_id}/run

        Manual Run

        Body fields: user_id (int), group_id (int), payload (Dict[str, Any])"""
        return self._t.request("POST", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/run", json=body)

    def set_settings(self, recipe_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/recipes/{recipe_id}/settings

        Update Settings

        Owner, editors and the hourly job limit. Owner or super admin only.

        Body fields: owner_id (int), editors (List[Any]), rate_limit_per_hour (int), clear_rate_limit (bool)"""
        return self._t.request("PUT", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/settings", json=body)

    def test(self, recipe_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/recipes/{recipe_id}/test

        Test Run

        Dry run of the DRAFT: nothing is written and no request is sent.

        Body fields: user_id (int), group_id (int), payload (Dict[str, Any])"""
        return self._t.request("POST", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/test", json=body)

    def get_versions(self, recipe_id: int) -> Any:
        """GET /api/v1/admin/recipes/{recipe_id}/versions

        Versions"""
        return self._t.request("GET", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/versions")

    def get_versions_by_recipe_id_version(self, recipe_id: int, version: int) -> Any:
        """GET /api/v1/admin/recipes/{recipe_id}/versions/{version}

        Get Version"""
        return self._t.request("GET", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/versions/{path_arg(version)}")

    def versions_restore(self, recipe_id: int, version: int) -> Any:
        """POST /api/v1/admin/recipes/{recipe_id}/versions/{version}/restore

        Restore Version

        Copy a published version into the draft. Nothing is published or enabled; the published version is untouched."""
        return self._t.request("POST", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/versions/{path_arg(version)}/restore")

    def webhook_secret(self, recipe_id: int) -> Any:
        """POST /api/v1/admin/recipes/{recipe_id}/webhook-secret

        Rotate Webhook Secret"""
        return self._t.request("POST", f"/api/v1/admin/recipes/{path_arg(recipe_id)}/webhook-secret")

    def hooks_recipes(self, public_id: str) -> Any:
        """POST /api/v1/hooks/recipes/{public_id}

        Webhook

        Needs a session: call client.login() first."""
        return self._t.request("POST", f"/api/v1/hooks/recipes/{path_arg(public_id)}")

class _Role:
    """Endpoints in the `role` section."""

    def __init__(self, t: Transport):
        self._t = t

    def role_admin(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/me/role/admin

        Switch To Admin View

        Regain admin powers for this session. Needs the current password (step-up), since it raises privilege.

        Body fields: password (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/role/admin", json=body)

    def role_user(self) -> Any:
        """POST /api/v1/me/role/user

        Switch To User View

        Drop admin powers for this session. No re-authentication needed: it only reduces privilege.

        Needs a session: call client.login() first."""
        return self._t.request("POST", "/api/v1/me/role/user")

class _Saml:
    """Endpoints in the `saml` section."""

    def __init__(self, t: Transport):
        self._t = t

    def saml_import_metadata(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/applications/saml/import-metadata

        Import Metadata

        Parse SP metadata pasted by the administrator (nothing is fetched from the network). Returns values to review, saves nothing.

        Body fields: xml (str, required)"""
        return self._t.request("POST", "/api/v1/admin/applications/saml/import-metadata", json=body)

    def get_saml_presets(self) -> Any:
        """GET /api/v1/admin/applications/saml/presets

        Presets"""
        return self._t.request("GET", "/api/v1/admin/applications/saml/presets")

    def saml_rotate_key(self) -> Any:
        """POST /api/v1/admin/applications/saml/rotate-key

        Rotate Key"""
        return self._t.request("POST", "/api/v1/admin/applications/saml/rotate-key")

    def delete_saml(self, app_id: int) -> Any:
        """DELETE /api/v1/admin/applications/{app_id}/saml

        Delete Saml"""
        return self._t.request("DELETE", f"/api/v1/admin/applications/{path_arg(app_id)}/saml")

    def get_saml(self, app_id: int) -> Any:
        """GET /api/v1/admin/applications/{app_id}/saml

        Get Saml"""
        return self._t.request("GET", f"/api/v1/admin/applications/{path_arg(app_id)}/saml")

    def set_saml(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/applications/{app_id}/saml

        Put Saml

        Body fields: sp_entity_id (str, required), acs_url (str, required), audience (str), name_id_format (str), name_id_attribute (str), signing (str), attribute_mappings (List[Any]), sp_cert (str), require_signed_requests (bool), default_relay_state (str), validity_seconds (int)"""
        return self._t.request("PUT", f"/api/v1/admin/applications/{path_arg(app_id)}/saml", json=body)

    def get_saml_preview(self, app_id: int, *, user_id: int) -> Any:
        """GET /api/v1/admin/applications/{app_id}/saml/preview

        Preview

        What this application would receive for a user (unsigned, nothing is issued). Lets an administrator check a JIT mapping."""
        return self._t.request("GET", f"/api/v1/admin/applications/{path_arg(app_id)}/saml/preview", query={"user_id": user_id})

    def saml_apps_respond(self, app_id: int) -> Any:
        """POST /api/v1/saml/apps/{app_id}/respond

        Idp Initiated

        Needs a session: call client.login() first."""
        return self._t.request("POST", f"/api/v1/saml/apps/{path_arg(app_id)}/respond")

    def get_saml_requests(self, request_id: str) -> Any:
        """GET /api/v1/saml/requests/{request_id}

        Get Request

        Needs a session: call client.login() first."""
        return self._t.request("GET", f"/api/v1/saml/requests/{path_arg(request_id)}")

    def saml_requests_respond(self, request_id: str) -> Any:
        """POST /api/v1/saml/requests/{request_id}/respond

        Respond

        Needs a session: call client.login() first."""
        return self._t.request("POST", f"/api/v1/saml/requests/{path_arg(request_id)}/respond")

    def get_saml_metadata(self, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """GET /saml/metadata

        Metadata

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("GET", "/saml/metadata", query=query)

    def get_saml_sso(self, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """GET /saml/sso

        Sso Redirect

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("GET", "/saml/sso", query=query)

    def saml_sso(self, form: Optional[Mapping[str, Any]] = None, *, query: Optional[Mapping[str, Any]] = None) -> Any:
        """POST /saml/sso

        Sso Post

        Protocol endpoint (not under /api/v1)."""
        return self._t.request("POST", "/saml/sso", query=query, form=form)

class _Scim:
    """Endpoints in the `scim` section."""

    def __init__(self, t: Transport):
        self._t = t

    def get_tokens(self) -> Any:
        """GET /api/v1/admin/scim/tokens

        List Tokens"""
        return self._t.request("GET", "/api/v1/admin/scim/tokens")

    def tokens(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/scim/tokens

        Create Token

        Body fields: name (str, required), expires_in_days (int), read_only (bool), users_only (bool), allowed_cidrs (List[Any]), hard_delete_after_days (int)"""
        return self._t.request("POST", "/api/v1/admin/scim/tokens", json=body)

    def delete_tokens(self, token_id: int) -> Any:
        """DELETE /api/v1/admin/scim/tokens/{token_id}

        Revoke Token"""
        return self._t.request("DELETE", f"/api/v1/admin/scim/tokens/{path_arg(token_id)}")

    def set_tokens_restrictions(self, token_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/scim/tokens/{token_id}/restrictions

        Restrict Token

        Narrow or widen what a token may do. Super admin only; every change is audited with before and after.

        Body fields: read_only (bool), users_only (bool), allowed_cidrs (List[Any]), hard_delete_after_days (int)"""
        return self._t.request("PUT", f"/api/v1/admin/scim/tokens/{path_arg(token_id)}/restrictions", json=body)

    def tokens_rotate(self, token_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/scim/tokens/{token_id}/rotate

        Rotate Token

        Issue a replacement with the same restrictions. The old token keeps working for `overlap_hours` (never longer than its own expiry) so the IdP can be switched over without a gap.

        Body fields: overlap_hours (int)"""
        return self._t.request("POST", f"/api/v1/admin/scim/tokens/{path_arg(token_id)}/rotate", json=body)

class _Search:
    """Endpoints in the `search` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self, *, q: str) -> Any:
        """GET /api/v1/admin/search

        Search"""
        return self._t.request("GET", "/api/v1/admin/search", query={"q": q})

class _SecurityPolicy:
    """Endpoints in the `security_policy` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self) -> Any:
        """GET /api/v1/admin/security-policy

        Read Policy"""
        return self._t.request("GET", "/api/v1/admin/security-policy")

    def replace(self, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/security-policy

        Write Policy

        Body fields: min_length (int, required), require_mixed_case (bool, required), require_digit (bool, required), require_symbol (bool, required), no_user_info (bool, required), history_count (int, required), max_age_days (int, required), max_failed_attempts (int, required), lockout_minutes (int, required), session_lifetime_hours (int, required), idle_timeout_minutes (int, required)"""
        return self._t.request("PUT", "/api/v1/admin/security-policy", json=body)

    def get_password_policy(self) -> Any:
        """GET /api/v1/password-policy

        Password Policy

        Unauthenticated: the rules a new password must meet (so the set-password page can show them). No other settings.

        Needs a session: call client.login() first."""
        return self._t.request("GET", "/api/v1/password-policy")

class _Swa:
    """Endpoints in the `swa` section."""

    def __init__(self, t: Transport):
        self._t = t

    def delete_swa(self, app_id: int) -> Any:
        """DELETE /api/v1/admin/applications/{app_id}/swa

        Delete Config"""
        return self._t.request("DELETE", f"/api/v1/admin/applications/{path_arg(app_id)}/swa")

    def get_swa(self, app_id: int) -> Any:
        """GET /api/v1/admin/applications/{app_id}/swa

        Get Config"""
        return self._t.request("GET", f"/api/v1/admin/applications/{path_arg(app_id)}/swa")

    def set_swa(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/admin/applications/{app_id}/swa

        Put Config

        Body fields: login_url (str, required), username_field (str, required), password_field (str, required), extra_fields (List[Any]), username_source (str)"""
        return self._t.request("PUT", f"/api/v1/admin/applications/{path_arg(app_id)}/swa", json=body)

    def get_swa_credentials(self, app_id: int) -> Any:
        """GET /api/v1/admin/applications/{app_id}/swa/credentials

        List Credentials

        Who has stored a credential. Never the secret, and the username only when the user typed it."""
        return self._t.request("GET", f"/api/v1/admin/applications/{path_arg(app_id)}/swa/credentials")

    def delete_swa_credentials(self, app_id: int, user_id: int) -> Any:
        """DELETE /api/v1/admin/applications/{app_id}/swa/credentials/{user_id}

        Reset Credential"""
        return self._t.request("DELETE", f"/api/v1/admin/applications/{path_arg(app_id)}/swa/credentials/{path_arg(user_id)}")

    def get_swa_apps(self, app_id: int) -> Any:
        """GET /api/v1/swa/apps/{app_id}

        Status

        Needs a session: call client.login() first."""
        return self._t.request("GET", f"/api/v1/swa/apps/{path_arg(app_id)}")

    def delete_swa_apps_credential(self, app_id: int) -> Any:
        """DELETE /api/v1/swa/apps/{app_id}/credential

        Remove Credential

        Needs a session: call client.login() first."""
        return self._t.request("DELETE", f"/api/v1/swa/apps/{path_arg(app_id)}/credential")

    def set_swa_apps_credential(self, app_id: int, body: Mapping[str, Any]) -> Any:
        """PUT /api/v1/swa/apps/{app_id}/credential

        Set Credential

        Body fields: username (str), password (str, required)

        Needs a session: call client.login() first."""
        return self._t.request("PUT", f"/api/v1/swa/apps/{path_arg(app_id)}/credential", json=body)

    def swa_apps_launch(self, app_id: int) -> Any:
        """POST /api/v1/swa/apps/{app_id}/launch

        Launch

        Needs a session: call client.login() first."""
        return self._t.request("POST", f"/api/v1/swa/apps/{path_arg(app_id)}/launch")

class _Users:
    """Endpoints in the `users` section."""

    def __init__(self, t: Transport):
        self._t = t

    def list(self, *, q: Optional[str] = None, status: Optional[str] = None, role: Optional[str] = None, start_index: Optional[int] = None, count: Optional[int] = None, sort_by: Optional[str] = None, sort_order: Optional[str] = None, filter: Optional[str] = None) -> Any:
        """GET /api/v1/admin/users

        List Users"""
        return self._t.request("GET", "/api/v1/admin/users", query={"q": q, "status": status, "role": role, "startIndex": start_index, "count": count, "sortBy": sort_by, "sortOrder": sort_order, "filter": filter})

    def create(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/users

        Create User

        Body fields: email (str), username (str), first_name (str, required), last_name (str, required), password (str), generate_password (bool), is_admin (bool), profile_attributes (Dict[str, Any]), group_ids (List[Any]), send_invite (bool)"""
        return self._t.request("POST", "/api/v1/admin/users", json=body)

    def bulk(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/users/bulk

        Bulk Action

        Apply one lifecycle action to many users. Each user is checked on its own; refusals are reported, not raised.

        Body fields: user_ids (List[Any], required), action (str, required)"""
        return self._t.request("POST", "/api/v1/admin/users/bulk", json=body)

    def get_suggest_identity(self, *, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Any:
        """GET /api/v1/admin/users/suggest-identity

        Suggest Identity

        What a new user with these names would be given (a preview: nothing is reserved until the user is created)."""
        return self._t.request("GET", "/api/v1/admin/users/suggest-identity", query={"first_name": first_name, "last_name": last_name})

    def delete(self, user_id: int) -> Any:
        """DELETE /api/v1/admin/users/{user_id}

        Delete User"""
        return self._t.request("DELETE", f"/api/v1/admin/users/{path_arg(user_id)}")

    def get(self, user_id: int) -> Any:
        """GET /api/v1/admin/users/{user_id}

        Get User"""
        return self._t.request("GET", f"/api/v1/admin/users/{path_arg(user_id)}")

    def update(self, user_id: int, body: Mapping[str, Any]) -> Any:
        """PATCH /api/v1/admin/users/{user_id}

        Update User

        Body fields: email (str), first_name (str), last_name (str), status (str), is_admin (bool), profile_attributes (Dict[str, Any])"""
        return self._t.request("PATCH", f"/api/v1/admin/users/{path_arg(user_id)}", json=body)

    def get_applications(self, user_id: int) -> Any:
        """GET /api/v1/admin/users/{user_id}/applications

        User Applications

        Applications this user may use, and whether that comes from a direct assignment or a group."""
        return self._t.request("GET", f"/api/v1/admin/users/{path_arg(user_id)}/applications")

    def get_events(self, user_id: int, *, page_size: Optional[int] = None) -> Any:
        """GET /api/v1/admin/users/{user_id}/events

        User Events

        Audit events about this user (as the target) or performed by them (as the actor)."""
        return self._t.request("GET", f"/api/v1/admin/users/{path_arg(user_id)}/events", query={"page_size": page_size})

    def password(self, user_id: int, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/users/{user_id}/password

        Reset Password

        Body fields: new_password (str, required), require_change (bool)"""
        return self._t.request("POST", f"/api/v1/admin/users/{path_arg(user_id)}/password", json=body)

    def send_invite(self, user_id: int) -> Any:
        """POST /api/v1/admin/users/{user_id}/send-invite

        Send Invite

        (Re)send the set-password email. Moves a staged account to provisioned. Not for active accounts."""
        return self._t.request("POST", f"/api/v1/admin/users/{path_arg(user_id)}/send-invite")

    def send_reset(self, user_id: int) -> Any:
        """POST /api/v1/admin/users/{user_id}/send-reset

        Send Reset

        Email the user a password-reset link (the admin never sees or sets the password)."""
        return self._t.request("POST", f"/api/v1/admin/users/{path_arg(user_id)}/send-reset")

class _UsersCsv:
    """Endpoints in the `users_csv` section."""

    def __init__(self, t: Transport):
        self._t = t

    def get_export_csv(self, *, q: Optional[str] = None, status: Optional[str] = None) -> Any:
        """GET /api/v1/admin/users/export.csv

        Export Users"""
        return self._t.request("GET", "/api/v1/admin/users/export.csv", query={"q": q, "status": status})

    def import_(self, body: Mapping[str, Any]) -> Any:
        """POST /api/v1/admin/users/import

        Import Users

        Body fields: csv (str, required), dry_run (bool), send_invite (bool), allow_repeat (bool)"""
        return self._t.request("POST", "/api/v1/admin/users/import", json=body)

    def get_import_columns(self) -> Any:
        """GET /api/v1/admin/users/import-columns

        Import Columns

        What each column means, for the import dialog."""
        return self._t.request("GET", "/api/v1/admin/users/import-columns")

    def get_import_template_csv(self) -> Any:
        """GET /api/v1/admin/users/import-template.csv

        Import Template"""
        return self._t.request("GET", "/api/v1/admin/users/import-template.csv")


class Namespaces:
    """One attribute per API section. Mixed into Client, which supplies the transport (self)."""

    def _attach(self) -> None:
        self.access_requests = _AccessRequests(self)  # type: ignore[arg-type]
        self.account_recovery = _AccountRecovery(self)  # type: ignore[arg-type]
        self.admin_roles = _AdminRoles(self)  # type: ignore[arg-type]
        self.administrators = _Administrators(self)  # type: ignore[arg-type]
        self.api_tokens = _ApiTokens(self)  # type: ignore[arg-type]
        self.applications = _Applications(self)  # type: ignore[arg-type]
        self.audit = _Audit(self)  # type: ignore[arg-type]
        self.bootstrap = _Bootstrap(self)  # type: ignore[arg-type]
        self.branding = _Branding(self)  # type: ignore[arg-type]
        self.connectors = _Connectors(self)  # type: ignore[arg-type]
        self.dashboard = _Dashboard(self)  # type: ignore[arg-type]
        self.features = _Features(self)  # type: ignore[arg-type]
        self.group_rules = _GroupRules(self)  # type: ignore[arg-type]
        self.groups = _Groups(self)  # type: ignore[arg-type]
        self.login_ = _Login(self)  # type: ignore[arg-type]
        self.logout = _Logout(self)  # type: ignore[arg-type]
        self.lookup_tables = _LookupTables(self)  # type: ignore[arg-type]
        self.me = _Me(self)  # type: ignore[arg-type]
        self.mfa = _Mfa(self)  # type: ignore[arg-type]
        self.oidc = _Oidc(self)  # type: ignore[arg-type]
        self.oidc_admin = _OidcAdmin(self)  # type: ignore[arg-type]
        self.oidc_clients = _OidcClients(self)  # type: ignore[arg-type]
        self.passkeys = _Passkeys(self)  # type: ignore[arg-type]
        self.policies = _Policies(self)  # type: ignore[arg-type]
        self.profile = _Profile(self)  # type: ignore[arg-type]
        self.profile_editor = _ProfileEditor(self)  # type: ignore[arg-type]
        self.provisioning = _Provisioning(self)  # type: ignore[arg-type]
        self.recipes = _Recipes(self)  # type: ignore[arg-type]
        self.role = _Role(self)  # type: ignore[arg-type]
        self.saml = _Saml(self)  # type: ignore[arg-type]
        self.scim = _Scim(self)  # type: ignore[arg-type]
        self.search = _Search(self)  # type: ignore[arg-type]
        self.security_policy = _SecurityPolicy(self)  # type: ignore[arg-type]
        self.swa = _Swa(self)  # type: ignore[arg-type]
        self.users = _Users(self)  # type: ignore[arg-type]
        self.users_csv = _UsersCsv(self)  # type: ignore[arg-type]


# Every operation in the OpenAPI document: (HTTP method, path, 'section.method').
OPERATIONS = [
    ("GET", "/api/v1/admin/access-requests", "access_requests.get_access_requests"),
    ("POST", "/api/v1/admin/access-requests/{request_id}/approve", "access_requests.access_requests_approve"),
    ("POST", "/api/v1/admin/access-requests/{request_id}/deny", "access_requests.access_requests_deny"),
    ("GET", "/api/v1/admin/applications/{app_id}/self-service", "access_requests.get_applications_self_service"),
    ("PUT", "/api/v1/admin/applications/{app_id}/self-service", "access_requests.set_applications_self_service"),
    ("GET", "/api/v1/me/access/catalog", "access_requests.get_access_catalog"),
    ("GET", "/api/v1/me/access/catalog/{app_id}/icon", "access_requests.get_access_catalog_icon"),
    ("GET", "/api/v1/me/access/requests", "access_requests.get_access_requests_me"),
    ("POST", "/api/v1/me/access/requests", "access_requests.access_requests"),
    ("POST", "/api/v1/me/access/requests/{request_id}/cancel", "access_requests.access_requests_cancel"),
    ("POST", "/api/v1/auth/change-expired-password", "account_recovery.change_expired_password"),
    ("POST", "/api/v1/auth/forgot-password", "account_recovery.forgot_password"),
    ("POST", "/api/v1/auth/reset-password", "account_recovery.reset_password"),
    ("GET", "/api/v1/admin/roles", "admin_roles.list"),
    ("GET", "/api/v1/admin/roles/groups", "admin_roles.get_groups"),
    ("GET", "/api/v1/admin/roles/groups/{group_id}", "admin_roles.get_groups_by_group_id"),
    ("PUT", "/api/v1/admin/roles/groups/{group_id}", "admin_roles.set_groups"),
    ("GET", "/api/v1/admin/roles/users/{user_id}", "admin_roles.get_users"),
    ("PUT", "/api/v1/admin/roles/users/{user_id}", "admin_roles.set_users"),
    ("GET", "/api/v1/me/admin-access", "admin_roles.get_me_admin_access"),
    ("GET", "/api/v1/admin/administrators", "administrators.list"),
    ("GET", "/api/v1/admin/api-tokens", "api_tokens.list"),
    ("POST", "/api/v1/admin/api-tokens", "api_tokens.create"),
    ("DELETE", "/api/v1/admin/api-tokens/{token_id}", "api_tokens.delete"),
    ("GET", "/api/v1/admin/applications", "applications.list"),
    ("POST", "/api/v1/admin/applications", "applications.create"),
    ("POST", "/api/v1/admin/applications/from-template", "applications.from_template"),
    ("GET", "/api/v1/admin/applications/templates", "applications.get_templates"),
    ("DELETE", "/api/v1/admin/applications/{app_id}", "applications.delete"),
    ("GET", "/api/v1/admin/applications/{app_id}", "applications.get"),
    ("PUT", "/api/v1/admin/applications/{app_id}", "applications.replace"),
    ("GET", "/api/v1/admin/applications/{app_id}/assignments", "applications.get_assignments"),
    ("POST", "/api/v1/admin/applications/{app_id}/assignments", "applications.assignments"),
    ("DELETE", "/api/v1/admin/applications/{app_id}/assignments/{assignment_id}", "applications.delete_assignments"),
    ("DELETE", "/api/v1/admin/applications/{app_id}/icon", "applications.delete_icon"),
    ("GET", "/api/v1/admin/applications/{app_id}/icon", "applications.get_icon"),
    ("PUT", "/api/v1/admin/applications/{app_id}/icon", "applications.set_icon"),
    ("DELETE", "/api/v1/admin/applications/{app_id}/oidc-client", "applications.delete_oidc_client"),
    ("POST", "/api/v1/admin/applications/{app_id}/oidc-client", "applications.oidc_client"),
    ("GET", "/api/v1/me/apps", "applications.get_me_apps"),
    ("GET", "/api/v1/me/apps/{app_id}/icon", "applications.get_me_apps_icon"),
    ("POST", "/api/v1/me/apps/{app_id}/launch", "applications.me_apps_launch"),
    ("GET", "/api/v1/admin/audit", "audit.list"),
    ("GET", "/api/v1/admin/audit/actions", "audit.get_actions"),
    ("GET", "/api/v1/admin/audit/export", "audit.get_export"),
    ("GET", "/api/v1/admin/stats", "audit.get_stats"),
    ("POST", "/api/v1/admin/bootstrap", "bootstrap.create"),
    ("GET", "/api/v1/admin/branding", "branding.list"),
    ("PUT", "/api/v1/admin/branding", "branding.replace"),
    ("DELETE", "/api/v1/admin/branding/logo", "branding.delete_logo"),
    ("PUT", "/api/v1/admin/branding/logo", "branding.set_logo"),
    ("GET", "/api/v1/admin/email-templates", "branding.get_email_templates"),
    ("DELETE", "/api/v1/admin/email-templates/{key}", "branding.delete_email_templates"),
    ("PUT", "/api/v1/admin/email-templates/{key}", "branding.set_email_templates"),
    ("POST", "/api/v1/admin/email-templates/{key}/preview", "branding.email_templates_preview"),
    ("POST", "/api/v1/admin/email-templates/{key}/send-test", "branding.email_templates_send_test"),
    ("GET", "/api/v1/branding", "branding.list_get"),
    ("GET", "/api/v1/branding/logo", "branding.get_logo"),
    ("GET", "/api/v1/admin/connectors", "connectors.list"),
    ("GET", "/api/v1/admin/connectors/{connector_id}", "connectors.get"),
    ("POST", "/api/v1/admin/connectors/{connector_id}/connections", "connectors.connections"),
    ("PUT", "/api/v1/admin/connectors/{connector_id}/connections/{cid}", "connectors.set_connections"),
    ("POST", "/api/v1/admin/recipe-connections/{cid}/test", "connectors.recipe_connections_test"),
    ("GET", "/api/v1/admin/dashboard", "dashboard.get_dashboard"),
    ("GET", "/api/v1/me/dashboard", "dashboard.get_dashboard_me"),
    ("GET", "/api/v1/me/dashboard/activity", "dashboard.get_dashboard_activity"),
    ("PUT", "/api/v1/me/dashboard/apps/{app_id}", "dashboard.set_dashboard_apps"),
    ("POST", "/api/v1/me/dashboard/import-favorites", "dashboard.dashboard_import_favorites"),
    ("POST", "/api/v1/me/dashboard/sections", "dashboard.dashboard_sections"),
    ("DELETE", "/api/v1/me/dashboard/sections/{section_id}", "dashboard.delete_dashboard_sections"),
    ("PATCH", "/api/v1/me/dashboard/sections/{section_id}", "dashboard.update_dashboard_sections"),
    ("GET", "/api/v1/admin/features", "features.list"),
    ("GET", "/api/v1/admin/group-rules", "group_rules.list"),
    ("POST", "/api/v1/admin/group-rules", "group_rules.create"),
    ("GET", "/api/v1/admin/group-rules/export", "group_rules.get_export"),
    ("GET", "/api/v1/admin/group-rules/expression-help", "group_rules.get_expression_help"),
    ("POST", "/api/v1/admin/group-rules/import", "group_rules.import_"),
    ("POST", "/api/v1/admin/group-rules/preview", "group_rules.preview"),
    ("GET", "/api/v1/admin/group-rules/template", "group_rules.get_template"),
    ("POST", "/api/v1/admin/group-rules/validate-expression", "group_rules.validate_expression"),
    ("DELETE", "/api/v1/admin/group-rules/{rule_id}", "group_rules.delete"),
    ("GET", "/api/v1/admin/group-rules/{rule_id}", "group_rules.get"),
    ("PUT", "/api/v1/admin/group-rules/{rule_id}", "group_rules.replace"),
    ("POST", "/api/v1/admin/group-rules/{rule_id}/activate", "group_rules.activate"),
    ("POST", "/api/v1/admin/group-rules/{rule_id}/deactivate", "group_rules.deactivate"),
    ("GET", "/api/v1/admin/groups", "groups.list"),
    ("POST", "/api/v1/admin/groups", "groups.create"),
    ("GET", "/api/v1/admin/groups/analytics", "groups.get_analytics"),
    ("GET", "/api/v1/admin/groups/standards", "groups.get_standards"),
    ("DELETE", "/api/v1/admin/groups/{group_id}", "groups.delete"),
    ("GET", "/api/v1/admin/groups/{group_id}", "groups.get"),
    ("PATCH", "/api/v1/admin/groups/{group_id}", "groups.update"),
    ("POST", "/api/v1/admin/groups/{group_id}/members", "groups.members"),
    ("DELETE", "/api/v1/admin/groups/{group_id}/members/{user_id}", "groups.delete_members"),
    ("POST", "/api/v1/login", "login_.create"),
    ("POST", "/api/v1/logout", "logout.create"),
    ("GET", "/api/v1/admin/lookup-tables", "lookup_tables.list"),
    ("POST", "/api/v1/admin/lookup-tables", "lookup_tables.create"),
    ("DELETE", "/api/v1/admin/lookup-tables/{tid}", "lookup_tables.delete"),
    ("GET", "/api/v1/admin/lookup-tables/{tid}", "lookup_tables.get"),
    ("PUT", "/api/v1/admin/lookup-tables/{tid}", "lookup_tables.replace"),
    ("GET", "/api/v1/admin/lookup-tables/{tid}/export", "lookup_tables.get_export"),
    ("POST", "/api/v1/admin/lookup-tables/{tid}/import", "lookup_tables.import_"),
    ("GET", "/api/v1/admin/lookup-tables/{tid}/rows", "lookup_tables.get_rows"),
    ("POST", "/api/v1/admin/lookup-tables/{tid}/rows", "lookup_tables.rows"),
    ("DELETE", "/api/v1/admin/lookup-tables/{tid}/rows/{rid}", "lookup_tables.delete_rows"),
    ("PUT", "/api/v1/admin/lookup-tables/{tid}/rows/{rid}", "lookup_tables.set_rows"),
    ("GET", "/api/v1/me", "me.list"),
    ("POST", "/api/v1/admin/users/{user_id}/enrollment-code", "mfa.users_enrollment_code"),
    ("POST", "/api/v1/admin/users/{user_id}/mfa/reset", "mfa.users_mfa_reset"),
    ("POST", "/api/v1/login/mfa", "mfa.login_mfa"),
    ("GET", "/api/v1/me/mfa", "mfa.get_mfa"),
    ("POST", "/api/v1/me/mfa/disable", "mfa.mfa_disable"),
    ("POST", "/api/v1/me/mfa/enable", "mfa.mfa_enable"),
    ("POST", "/api/v1/me/mfa/recovery-codes", "mfa.mfa_recovery_codes"),
    ("POST", "/api/v1/me/mfa/setup", "mfa.mfa_setup"),
    ("GET", "/.well-known/openid-configuration", "oidc.get_well_known_openid_configuration"),
    ("GET", "/api/v1/me/consents", "oidc.get_me_consents"),
    ("DELETE", "/api/v1/me/consents/{client_pk}", "oidc.delete_me_consents"),
    ("GET", "/api/v1/oidc/authorization-requests/{request_id}", "oidc.get_oidc_authorization_requests"),
    ("POST", "/api/v1/oidc/authorization-requests/{request_id}/decision", "oidc.oidc_authorization_requests_decision"),
    ("POST", "/api/v1/oidc/logout", "oidc.oidc_logout"),
    ("GET", "/api/v1/oidc/logout-request", "oidc.get_oidc_logout_request"),
    ("GET", "/oauth/authorize", "oidc.get_authorize"),
    ("POST", "/oauth/introspect", "oidc.introspect"),
    ("GET", "/oauth/jwks", "oidc.get_jwks"),
    ("GET", "/oauth/logout", "oidc.get_logout"),
    ("POST", "/oauth/logout", "oidc.logout"),
    ("POST", "/oauth/revoke", "oidc.revoke"),
    ("POST", "/oauth/token", "oidc.token_post"),
    ("GET", "/oauth/userinfo", "oidc.get_userinfo"),
    ("POST", "/oauth/userinfo", "oidc.userinfo"),
    ("GET", "/api/v1/admin/oidc/keys", "oidc_admin.get_keys"),
    ("POST", "/api/v1/admin/oidc/keys/rotate", "oidc_admin.keys_rotate"),
    ("GET", "/api/v1/admin/oidc/clients", "oidc_clients.get_clients"),
    ("POST", "/api/v1/admin/oidc/clients", "oidc_clients.clients"),
    ("DELETE", "/api/v1/admin/oidc/clients/{pk}", "oidc_clients.delete_clients"),
    ("GET", "/api/v1/admin/oidc/clients/{pk}", "oidc_clients.get_clients_by_pk"),
    ("PATCH", "/api/v1/admin/oidc/clients/{pk}", "oidc_clients.update_clients"),
    ("POST", "/api/v1/admin/oidc/clients/{pk}/secrets", "oidc_clients.clients_secrets"),
    ("DELETE", "/api/v1/admin/oidc/clients/{pk}/secrets/{secret_id}", "oidc_clients.delete_clients_secrets"),
    ("POST", "/api/v1/login/passkey/options", "passkeys.login_passkey_options"),
    ("POST", "/api/v1/login/passkey/verify", "passkeys.login_passkey_verify"),
    ("GET", "/api/v1/me/passkeys", "passkeys.get_passkeys"),
    ("POST", "/api/v1/me/passkeys/policy", "passkeys.passkeys_policy"),
    ("POST", "/api/v1/me/passkeys/register/options", "passkeys.passkeys_register_options"),
    ("POST", "/api/v1/me/passkeys/register/verify", "passkeys.passkeys_register_verify"),
    ("PATCH", "/api/v1/me/passkeys/{passkey_id}", "passkeys.update_passkeys"),
    ("POST", "/api/v1/me/passkeys/{passkey_id}/remove", "passkeys.passkeys_remove"),
    ("DELETE", "/api/v1/admin/applications/{app_id}/policy", "policies.delete_applications_policy"),
    ("GET", "/api/v1/admin/applications/{app_id}/policy", "policies.get_applications_policy"),
    ("PUT", "/api/v1/admin/applications/{app_id}/policy", "policies.set_applications_policy"),
    ("GET", "/api/v1/admin/network-zones", "policies.list"),
    ("POST", "/api/v1/admin/network-zones", "policies.create"),
    ("DELETE", "/api/v1/admin/network-zones/{zone_id}", "policies.delete"),
    ("PUT", "/api/v1/admin/network-zones/{zone_id}", "policies.replace"),
    ("GET", "/api/v1/me/activity", "profile.get_activity"),
    ("POST", "/api/v1/me/password", "profile.password"),
    ("GET", "/api/v1/me/profile", "profile.get_profile"),
    ("PATCH", "/api/v1/me/profile", "profile.update_profile"),
    ("GET", "/api/v1/me/sessions", "profile.get_sessions"),
    ("GET", "/api/v1/admin/profile-attributes", "profile_editor.list"),
    ("POST", "/api/v1/admin/profile-attributes", "profile_editor.create"),
    ("DELETE", "/api/v1/admin/profile-attributes/{key}", "profile_editor.delete"),
    ("PATCH", "/api/v1/admin/profile-attributes/{key}", "profile_editor.update"),
    ("GET", "/api/v1/admin/provisioning-apps", "provisioning.list"),
    ("POST", "/api/v1/admin/provisioning-apps", "provisioning.create"),
    ("GET", "/api/v1/admin/provisioning-apps/mapping", "provisioning.get_mapping"),
    ("GET", "/api/v1/admin/provisioning-apps/presets", "provisioning.get_presets"),
    ("DELETE", "/api/v1/admin/provisioning-apps/{app_id}", "provisioning.delete"),
    ("GET", "/api/v1/admin/provisioning-apps/{app_id}", "provisioning.get"),
    ("PUT", "/api/v1/admin/provisioning-apps/{app_id}", "provisioning.replace"),
    ("GET", "/api/v1/admin/provisioning-apps/{app_id}/assignments", "provisioning.get_assignments"),
    ("POST", "/api/v1/admin/provisioning-apps/{app_id}/assignments", "provisioning.assignments"),
    ("DELETE", "/api/v1/admin/provisioning-apps/{app_id}/assignments/{assignment_id}", "provisioning.delete_assignments"),
    ("POST", "/api/v1/admin/provisioning-apps/{app_id}/deprovision-all", "provisioning.deprovision_all"),
    ("GET", "/api/v1/admin/provisioning-apps/{app_id}/links", "provisioning.get_links"),
    ("GET", "/api/v1/admin/provisioning-apps/{app_id}/preview", "provisioning.get_preview"),
    ("POST", "/api/v1/admin/provisioning-apps/{app_id}/sync", "provisioning.sync"),
    ("GET", "/api/v1/admin/provisioning-apps/{app_id}/tasks", "provisioning.get_tasks"),
    ("POST", "/api/v1/admin/provisioning-apps/{app_id}/tasks/{task_id}/retry", "provisioning.tasks_retry"),
    ("POST", "/api/v1/admin/provisioning-apps/{app_id}/test", "provisioning.test"),
    ("GET", "/api/v1/admin/recipe-connections", "recipes.get_recipe_connections"),
    ("POST", "/api/v1/admin/recipe-connections", "recipes.recipe_connections"),
    ("DELETE", "/api/v1/admin/recipe-connections/{cid}", "recipes.delete_recipe_connections"),
    ("PUT", "/api/v1/admin/recipe-connections/{cid}", "recipes.set_recipe_connections"),
    ("GET", "/api/v1/admin/recipes", "recipes.list"),
    ("POST", "/api/v1/admin/recipes", "recipes.create"),
    ("POST", "/api/v1/admin/recipes/from-template", "recipes.from_template"),
    ("POST", "/api/v1/admin/recipes/import", "recipes.import_"),
    ("GET", "/api/v1/admin/recipes/jobs", "recipes.get_jobs"),
    ("GET", "/api/v1/admin/recipes/jobs/{job_id}", "recipes.get_jobs_by_job_id"),
    ("POST", "/api/v1/admin/recipes/jobs/{job_id}/approve", "recipes.jobs_approve"),
    ("POST", "/api/v1/admin/recipes/jobs/{job_id}/cancel", "recipes.jobs_cancel"),
    ("POST", "/api/v1/admin/recipes/jobs/{job_id}/deny", "recipes.jobs_deny"),
    ("POST", "/api/v1/admin/recipes/jobs/{job_id}/rerun", "recipes.jobs_rerun"),
    ("GET", "/api/v1/admin/recipes/meta", "recipes.get_meta"),
    ("GET", "/api/v1/admin/recipes/metrics", "recipes.get_metrics"),
    ("GET", "/api/v1/admin/recipes/status", "recipes.get_status"),
    ("GET", "/api/v1/admin/recipes/templates", "recipes.get_templates"),
    ("DELETE", "/api/v1/admin/recipes/{recipe_id}", "recipes.delete"),
    ("GET", "/api/v1/admin/recipes/{recipe_id}", "recipes.get"),
    ("PUT", "/api/v1/admin/recipes/{recipe_id}", "recipes.replace"),
    ("GET", "/api/v1/admin/recipes/{recipe_id}/callers", "recipes.get_callers"),
    ("POST", "/api/v1/admin/recipes/{recipe_id}/disable", "recipes.disable"),
    ("POST", "/api/v1/admin/recipes/{recipe_id}/enable", "recipes.enable"),
    ("GET", "/api/v1/admin/recipes/{recipe_id}/export", "recipes.get_export"),
    ("POST", "/api/v1/admin/recipes/{recipe_id}/formula-preview", "recipes.formula_preview"),
    ("POST", "/api/v1/admin/recipes/{recipe_id}/publish", "recipes.publish"),
    ("POST", "/api/v1/admin/recipes/{recipe_id}/run", "recipes.run"),
    ("PUT", "/api/v1/admin/recipes/{recipe_id}/settings", "recipes.set_settings"),
    ("POST", "/api/v1/admin/recipes/{recipe_id}/test", "recipes.test"),
    ("GET", "/api/v1/admin/recipes/{recipe_id}/versions", "recipes.get_versions"),
    ("GET", "/api/v1/admin/recipes/{recipe_id}/versions/{version}", "recipes.get_versions_by_recipe_id_version"),
    ("POST", "/api/v1/admin/recipes/{recipe_id}/versions/{version}/restore", "recipes.versions_restore"),
    ("POST", "/api/v1/admin/recipes/{recipe_id}/webhook-secret", "recipes.webhook_secret"),
    ("POST", "/api/v1/hooks/recipes/{public_id}", "recipes.hooks_recipes"),
    ("POST", "/api/v1/me/role/admin", "role.role_admin"),
    ("POST", "/api/v1/me/role/user", "role.role_user"),
    ("POST", "/api/v1/admin/applications/saml/import-metadata", "saml.saml_import_metadata"),
    ("GET", "/api/v1/admin/applications/saml/presets", "saml.get_saml_presets"),
    ("POST", "/api/v1/admin/applications/saml/rotate-key", "saml.saml_rotate_key"),
    ("DELETE", "/api/v1/admin/applications/{app_id}/saml", "saml.delete_saml"),
    ("GET", "/api/v1/admin/applications/{app_id}/saml", "saml.get_saml"),
    ("PUT", "/api/v1/admin/applications/{app_id}/saml", "saml.set_saml"),
    ("GET", "/api/v1/admin/applications/{app_id}/saml/preview", "saml.get_saml_preview"),
    ("POST", "/api/v1/saml/apps/{app_id}/respond", "saml.saml_apps_respond"),
    ("GET", "/api/v1/saml/requests/{request_id}", "saml.get_saml_requests"),
    ("POST", "/api/v1/saml/requests/{request_id}/respond", "saml.saml_requests_respond"),
    ("GET", "/saml/metadata", "saml.get_saml_metadata"),
    ("GET", "/saml/sso", "saml.get_saml_sso"),
    ("POST", "/saml/sso", "saml.saml_sso"),
    ("GET", "/api/v1/admin/scim/tokens", "scim.get_tokens"),
    ("POST", "/api/v1/admin/scim/tokens", "scim.tokens"),
    ("DELETE", "/api/v1/admin/scim/tokens/{token_id}", "scim.delete_tokens"),
    ("PUT", "/api/v1/admin/scim/tokens/{token_id}/restrictions", "scim.set_tokens_restrictions"),
    ("POST", "/api/v1/admin/scim/tokens/{token_id}/rotate", "scim.tokens_rotate"),
    ("GET", "/api/v1/admin/search", "search.list"),
    ("GET", "/api/v1/admin/security-policy", "security_policy.list"),
    ("PUT", "/api/v1/admin/security-policy", "security_policy.replace"),
    ("GET", "/api/v1/password-policy", "security_policy.get_password_policy"),
    ("DELETE", "/api/v1/admin/applications/{app_id}/swa", "swa.delete_swa"),
    ("GET", "/api/v1/admin/applications/{app_id}/swa", "swa.get_swa"),
    ("PUT", "/api/v1/admin/applications/{app_id}/swa", "swa.set_swa"),
    ("GET", "/api/v1/admin/applications/{app_id}/swa/credentials", "swa.get_swa_credentials"),
    ("DELETE", "/api/v1/admin/applications/{app_id}/swa/credentials/{user_id}", "swa.delete_swa_credentials"),
    ("GET", "/api/v1/swa/apps/{app_id}", "swa.get_swa_apps"),
    ("DELETE", "/api/v1/swa/apps/{app_id}/credential", "swa.delete_swa_apps_credential"),
    ("PUT", "/api/v1/swa/apps/{app_id}/credential", "swa.set_swa_apps_credential"),
    ("POST", "/api/v1/swa/apps/{app_id}/launch", "swa.swa_apps_launch"),
    ("GET", "/api/v1/admin/users", "users.list"),
    ("POST", "/api/v1/admin/users", "users.create"),
    ("POST", "/api/v1/admin/users/bulk", "users.bulk"),
    ("GET", "/api/v1/admin/users/suggest-identity", "users.get_suggest_identity"),
    ("DELETE", "/api/v1/admin/users/{user_id}", "users.delete"),
    ("GET", "/api/v1/admin/users/{user_id}", "users.get"),
    ("PATCH", "/api/v1/admin/users/{user_id}", "users.update"),
    ("GET", "/api/v1/admin/users/{user_id}/applications", "users.get_applications"),
    ("GET", "/api/v1/admin/users/{user_id}/events", "users.get_events"),
    ("POST", "/api/v1/admin/users/{user_id}/password", "users.password"),
    ("POST", "/api/v1/admin/users/{user_id}/send-invite", "users.send_invite"),
    ("POST", "/api/v1/admin/users/{user_id}/send-reset", "users.send_reset"),
    ("GET", "/api/v1/admin/users/export.csv", "users_csv.get_export_csv"),
    ("POST", "/api/v1/admin/users/import", "users_csv.import_"),
    ("GET", "/api/v1/admin/users/import-columns", "users_csv.get_import_columns"),
    ("GET", "/api/v1/admin/users/import-template.csv", "users_csv.get_import_template_csv"),
]
