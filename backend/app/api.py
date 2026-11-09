"""FastAPI application and API router configuration."""

from fastapi import FastAPI, HTTPException
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


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="IdentityForge API",
        description="Identity and Access Management Platform",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS: explicit origins only (credentials are allowed, so never "*"). The OIDC protocol endpoints are not
    # credentialed and set their own narrow headers (oidc/cors.py), so the cookie-API policy stays out of their way.
    app.add_middleware(
        _AppCORS,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    )

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
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_exception_handler(request, exc):
        """Handle database errors."""
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal database error"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        """Handle validation errors."""
        return JSONResponse(
            status_code=422,
            # Drop ctx (may hold non-serialisable exceptions) and input (may echo passwords)
            content={
                "detail": [
                    {k: v for k, v in e.items() if k not in ("ctx", "input")}
                    for e in exc.errors()
                ]
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc):
        """Handle unexpected exceptions."""
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # Include auth routes (defined in backend/app/auth/routes.py)
    from backend.app.auth.routes import router as auth_router
    app.include_router(auth_router, prefix="/api/v1")
    from backend.app.auth.recovery_routes import router as recovery_router

    app.include_router(recovery_router, prefix="/api/v1")

    from backend.app.dashboard import router as dashboard_router
    from backend.app.audit.routes import router as audit_router
    from backend.app.auth.mfa_routes import router as mfa_router
    from backend.app.auth.passkey_routes import router as passkey_router
    from backend.app.auth.role_routes import router as role_router
    from backend.app.groups.routes import router as groups_router
    from backend.app.profiles.routes import router as profiles_router
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
    from backend.app.recipes.routes import hooks_router as recipe_hooks_router
    from backend.app.recipes.routes import router as recipes_router

    for r in (recipes_router, recipe_conn_router, recipe_hooks_router):
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
    app.mount("/scim/v2", create_scim_app())  # SCIM 2.0 server (ADR 007): own error format, bearer-token auth

    from backend.app.search_routes import router as search_router

    app.include_router(search_router, prefix="/api/v1")
    for r in (users_router, groups_router, profiles_router, audit_router, dashboard_router, mfa_router, passkey_router, role_router):
        app.include_router(r, prefix="/api/v1")

    return app


# Create and export the app
app = create_app()