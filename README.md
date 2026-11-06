# IdentityForge

Identity and Access Management Platform built from scratch, not a rebranded solution.

## Overview

IdentityForge provides a comprehensive identity management solution with:
- User and Group management
- Secure authentication with Argon2id password hashing
- Session management with cryptographically secure tokens
- Audit logging for compliance
- Admin and end-user dashboards

## Phase 1 Features

- [x] Docker Compose stack
- [x] PostgreSQL data store
- [x] Redis session cache
- [x] One-time administrator bootstrap
- [x] Secure login/logout
- [x] Session management
- [x] Admin RBAC
- [x] User/Group CRUD
- [x] Profile attributes
- [x] System audit events
- [x] Admin dashboard
- [x] End-user dashboard

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.12+ (for development)
- Node.js 20+ (for frontend development)

### Start the Platform

```bash
cd docker
docker-compose up -d
```

### Bootstrap Administrator

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Generate secure keys:
```bash
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('ADMIN_SECRET_KEY=' + secrets.token_urlsafe(32))"
```

3. Update `.env` with your keys

4. Bootstrap admin (via API or script):
```bash
curl -X POST http://localhost:8000/api/v1/admin/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@identityforge.local","password":"YourSecurePassword123!","first_name":"System","last_name":"Administrator","secret_key":"your-admin-secret-key"}'
```

### Access the UI

- Admin Dashboard: http://localhost:3000/admin/dashboard
- User Portal: http://localhost:3000/user/dashboard
- API Docs: http://localhost:8000/docs

## Architecture

### Backend
- **Framework**: FastAPI with Python 3.12
- **Database**: PostgreSQL with SQLAlchemy 2
- **Session Store**: Redis + PostgreSQL
- **Password Hashing**: Argon2id
- **Session Tokens**: Cryptographically secure opaque tokens

### Frontend
- **Framework**: Next.js App Router
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **State**: React Hooks

### Infrastructure
- **Containers**: Docker Compose
- **Database**: PostgreSQL 16
- **Cache**: Redis 7

## Development

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Testing

### Run Backend Tests
```bash
cd backend
pytest tests/ -v --cov=app --cov-report=html
```

### Run Frontend Tests
```bash
cd frontend
npm test
```

## Security

- Passwords hashed with Argon2id
- Session tokens are 256-bit cryptographically secure
- Secure cookie flags (HttpOnly, SameSite)
- Account lockout after failed attempts
- Audit logging for all sensitive operations

## License

Proprietary - IdentityForge Development