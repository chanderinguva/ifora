# IdentityForge Engineering Guidelines

## Mission
Build a production-oriented, custom Identity and Access Management platform.

## Core Principles
- Real end-to-end features, no mock data
- Modular monolith with deployable workers
- PostgreSQL authoritative data store
- Strict authorization boundaries
- Standards-compliant identity protocols
- Mature cryptographic libraries only
- Test before security shortcuts

## Technology Stack
**Backend:** Python 3.12+, FastAPI, SQLAlchemy 2, PostgreSQL, Redis
**Frontend:** Next.js App Router, React, TypeScript, Tailwind CSS
**Deployment:** Docker Compose, named volumes, health checks

## Security Requirements
- Argon2id password hashing
- Cryptographically random opaque sessions
- Secure HttpOnly SameSite cookies
- CSRF protection
- Account enumeration resistance
- Deny-by-default authorization

## Phase 1 Scope
- Docker Compose stack
- Database migrations
- Admin bootstrap & login
- End-user login & logout
- Session management
- Admin RBAC
- User/Group CRUD
- Profile attributes
- System audit events
- Admin & user dashboards
- Browser & API tests

## Repository Structure
```
identityforge/
├── backend/
│   ├── app/
│   │   ├── auth/
│   │   ├── users/
│   │   ├── groups/
│   │   ├── profiles/
│   │   ├── audit/
│   │   ├── api.py
│   │   └── main.py
│   ├── migrations/
│   └── requirements.txt
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── package.json
├── docker/
│   ├── backend/
│   ├── frontend/
│   └── docker-compose.yml
├── docs/
│   └── project/
└── .claude/agents/
```

## Agent Coordination
Use orchestrator to assign tasks, verify dependencies, and gate releases.

## Definition of Done
All Phase 1 items complete with tests, security review, and documentation.