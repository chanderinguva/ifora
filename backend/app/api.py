"""FastAPI application and API router configuration."""

import logging

from starlette.concurrency import run_in_threadpool

from fastapi import FastAPI
from starlette.exceptions import HTTPException   # the base class, so unknown routes and 405s are covered too

from backend.app.scim.envelope import ScimEnvelopeMiddleware
from backend.app.scim.errors import problem
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import settings


async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "environment": settings.ENVIRONMENT}


OIDC_PUBLIC_PREFIXES = ("/oauth/token", "/oauth/userinfo", "/oauth/jwks", "/oauth/revoke", "/.well-known/")


class _AppCORS(CORSMiddleware):
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(OIDC_PUBLIC_PREFIXES):
            return await self.app(scope, receive, send)
        return await super().__call__(scope, receive, send)


class TenantIssuerMiddleware:
    """Multi-tenant mode: resolve the tenant from the Host header once per request, bind its issuer for the handlers
    (tenancy.issuer()) and answer 404 for an unknown host before any route runs. Single-tenant mode: a no-op. Only the
    Host header is read; X-Forwarded-Host and friends are ignored."""

    OPEN_PATHS = ("/health",)  # probes carry arbitrary Host headers

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or settings.TENANT_RESOLUTION != "host" or scope["path"] in self.OPEN_PATHS:
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse as _J

        from backend.app.tenancy import TenantNotResolved, reset_request_issuer, resolve_tenant, set_request_issuer

        host = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"host"), None)
        try:
            _, iss = await run_in_threadpool(resolve_tenant, host)
        except TenantNotResolved:
            return await _J({"detail": "Not found"}, status_code=404)(scope, receive, send)
        except Exception:  # noqa: BLE001 - a resolver fault must never fall back to another tenant
            logging.getLogger(__name__).exception("tenant resolution failed")
            return await _J({"detail": "Service temporarily unavailable"}, status_code=503)(scope, receive, send)
        token = set_request_issuer(iss)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_request_issuer(token)


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from backend.app import config_guards

    prod = config_guards.is_production(settings)
    problems = config_guards.validate_settings(settings)
    if problems:  # fail closed: an unsafe production configuration refuses to boot (messages never contain values)
        raise RuntimeError("Refusing to start in production: " + "; ".join(problems))
    proxy_warned = {"done": False}
    app = FastAPI(
        title="Ifora API",
        description="Identity and Access Management Platform",
        version="0.1.0",
        docs_url=None if prod else "/docs",
        redoc_url=None if prod else "/redoc",
        openapi_url=None if prod else "/openapi.json",
    )

    app.add_middleware(ScimEnvelopeMiddleware)   # innermost: schemas + meta on every JSON resource and list under /api/v1

    @app.middleware("http")
    async def security_headers(request, call_next):
        if prod and not proxy_warned["done"] and "x-forwarded-for" in request.headers and config_guards.forwarded_ips_is_default():
            # uvicorn ignores the header unless the peer is in FORWARDED_ALLOW_IPS, so every client looks like the proxy
            # (throttling, lockout and IP/CIDR policies then see one address). Say so once, loudly.
            proxy_warned["done"] = True
            logging.getLogger(__name__).error(
                "X-Forwarded-For received but FORWARDED_ALLOW_IPS is the default (127.0.0.1): the header is NOT trusted and "
                "all clients share the proxy address. Set FORWARDED_ALLOW_IPS to your proxy's address."
            )
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("X-Frame-Options", "DENY")
        if settings.SESSION_COOKIE_SECURE:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    # CORS: explicit origins only (credentials are allowed, so never "*"). The OIDC protocol endpoints are not
    # credentialed and set their own narrow headers (oidc/cors.py), so the cookie-API policy stays out of their way.
    app.add_middleware(
        _AppCORS,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    )

    app.add_middleware(TenantIssuerMiddleware)  # outermost: every handler sees the tenant's issuer, unknown hosts end here

    # Health check endpoint
    from backend.app.metrics import router as metrics_router

    app.include_router(metrics_router)

    @app.get("/health", include_in_schema=False)
    async def health():
        """Health check endpoint."""
        return await health_check()

    # Error handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        """Handle HTTP exceptions consistently."""
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        body = problem(exc.status_code, detail)
        if not isinstance(exc.detail, str):
            body["errors"] = exc.detail   # structured detail some routes raise
        return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))

    @app.exception_handler(SQLAlchemyError)
    async def db_exception_handler(request, exc):
        """Handle database errors."""
        return JSONResponse(status_code=500, content=problem(500, "Internal database error"))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        """Handle validation errors: SCIM Error with a readable detail, and the per-field list under `errors`."""
        # Drop ctx (may hold non-serialisable exceptions) and input (may echo passwords)
        errors = [{k: v for k, v in e.items() if k not in ("ctx", "input")} for e in exc.errors()]
        parts = []
        for e in errors:
            field = ".".join(str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path"))
            parts.append(f"{field}: {e.get('msg', 'invalid')}" if field else str(e.get("msg", "invalid")))
        body = problem(422, "; ".join(parts) or "Invalid request", "invalidValue")
        body["errors"] = errors
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc):
        """Handle unexpected exceptions."""
        return JSONResponse(status_code=500, content=problem(500, "Internal server error"))

    # Include auth routes (defined in backend/app/auth/routes.py)
    from backend.app.auth.routes import router as auth_router
    app.include_router(auth_router, prefix="/api/v1")
    from backend.app.auth.access_sso import router as access_sso_router

    app.include_router(access_sso_router, prefix="/api/v1")
    from backend.app.auth.recovery_routes import router as recovery_router

    app.include_router(recovery_router, prefix="/api/v1")

    from backend.app.dashboard import router as dashboard_router
    from backend.app.audit.routes import router as audit_router
    from backend.app.auth.mfa_routes import router as mfa_router
    from backend.app.auth.passkey_routes import router as passkey_router
    from backend.app.auth.role_routes import router as role_router
    from backend.app.groups.routes import router as groups_router
    from backend.app.profiles.avatar import router as avatar_router
    from backend.app.profiles.routes import router as profiles_router
    from backend.app.users.csv_routes import router as users_csv_router
    from backend.app.users.routes import router as users_router

    from backend.app.oidc.routes import admin_router as oidc_admin_router, public_router as oidc_public_router

    from backend.app.groups.rule_routes import features_router, router as group_rules_router

    app.include_router(group_rules_router, prefix="/api/v1")
    app.include_router(features_router, prefix="/api/v1")
    from backend.app.oidc.authorize_routes import api_router as oidc_authz_api, public_router as oidc_authz_public

    app.include_router(oidc_authz_public)
    from backend.app.oidc.token_routes import router as oidc_token_router

    app.include_router(oidc_token_router)
    from backend.app.oidc.logout_routes import api_router as oidc_logout_api, public_router as oidc_logout_public

    app.include_router(oidc_logout_public)
    app.include_router(oidc_logout_api, prefix="/api/v1")
    from backend.app.oidc.consent_routes import router as oidc_consent_router

    app.include_router(oidc_consent_router, prefix="/api/v1")
    app.include_router(oidc_authz_api, prefix="/api/v1")
    app.include_router(oidc_public_router)  # issuer-root endpoints: /oauth/*, later /.well-known/*
    from backend.app.oidc.client_routes import router as oidc_clients_router

    from backend.app.profiles.attribute_routes import router as profile_attr_router

    app.include_router(profile_attr_router, prefix="/api/v1")
    app.include_router(oidc_admin_router, prefix="/api/v1")
    app.include_router(oidc_clients_router, prefix="/api/v1")

    from backend.app.recipes.routes import connections_router as recipe_conn_router
    from backend.app.recipes.lookup_routes import router as lookup_router
    from backend.app.recipes.routes import hooks_router as recipe_hooks_router
    from backend.app.recipes.routes import router as recipes_router

    from backend.app.connectors.routes import router as connectors_router
    from backend.app.connectors.routes import tests_router as connector_tests_router
    from backend.app.recipes.connection_routes import router as connection_workspaces_router
    from backend.app.recipes.oauth_logs import install as install_oauth_log_filter
    install_oauth_log_filter()
    app.include_router(connection_workspaces_router, prefix="/api/v1")

    for r in (recipes_router, recipe_conn_router, connector_tests_router, recipe_hooks_router, lookup_router, connectors_router):
        app.include_router(r, prefix="/api/v1")
    from backend.app.applications.routes import me_router as my_apps_router
    from backend.app.applications.routes import router as applications_router
    from backend.app.provisioning.routes import router as provisioning_router

    from backend.app.saml.routes import admin_router as saml_admin, api_router as saml_api, public_router as saml_public

    app.include_router(saml_admin, prefix="/api/v1")  # before applications_router: /admin/applications/saml/* must win over /{app_id}
    app.include_router(saml_api, prefix="/api/v1")
    app.include_router(saml_public)
    from backend.app.swa.routes import admin_router as swa_admin, api_router as swa_api

    from backend.app.branding.routes import public_router as branding_public, router as branding_admin, templates_router as email_templates_router
    from backend.app.admin_roles.routes import me_router as admin_access_router, router as admin_roles_router
    from backend.app.policies.routes import policy_router, zones_router

    for r in (branding_public, branding_admin, email_templates_router):
        app.include_router(r, prefix="/api/v1")
    app.include_router(admin_roles_router, prefix="/api/v1")
    from backend.app.dashboard_prefs.routes import router as dashboard_prefs_router

    app.include_router(dashboard_prefs_router, prefix="/api/v1")
    from backend.app.access_requests.routes import admin_router as access_admin, me_router as access_me, settings_router as access_settings

    app.include_router(access_admin, prefix="/api/v1")
    from backend.app.security_policy.routes import public_router as sec_public, router as sec_admin

    app.include_router(sec_admin, prefix="/api/v1")
    app.include_router(sec_public, prefix="/api/v1")
    app.include_router(access_settings, prefix="/api/v1")
    app.include_router(access_me, prefix="/api/v1")
    app.include_router(admin_access_router, prefix="/api/v1")

    app.include_router(zones_router, prefix="/api/v1")
    app.include_router(policy_router, prefix="/api/v1")  # before applications_router: /{app_id}/policy
    app.include_router(swa_admin, prefix="/api/v1")
    app.include_router(swa_api, prefix="/api/v1")
    app.include_router(applications_router, prefix="/api/v1")
    app.include_router(my_apps_router, prefix="/api/v1")

    app.include_router(provisioning_router, prefix="/api/v1")
    from backend.app.scim.admin_routes import router as scim_admin_router
    from backend.app.scim.app import create_scim_app

    app.include_router(scim_admin_router, prefix="/api/v1")
    from backend.app.api_tokens.administrators import router as administrators_router
    from backend.app.api_tokens.routes import router as api_tokens_router

    app.include_router(api_tokens_router, prefix="/api/v1")
    app.include_router(administrators_router, prefix="/api/v1")
    app.mount("/scim/v2", create_scim_app())  # SCIM 2.0 server (ADR 007): own error format, bearer-token auth

    from backend.app.search_routes import router as search_router
    from backend.app.integrations.slack_ideas import router as slack_idea_router

    app.include_router(search_router, prefix="/api/v1")
    app.include_router(slack_idea_router, prefix="/api/v1")
    for r in (users_csv_router, users_router, groups_router, profiles_router, avatar_router, audit_router, dashboard_router, mfa_router, passkey_router, role_router):
        app.include_router(r, prefix="/api/v1")

    return app


# Create and export the app
app = create_app()
