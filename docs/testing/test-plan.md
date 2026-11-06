# IdentityForge Test Plan

## Overview
Comprehensive test strategy for IdentityForge Phase 1 implementation.

## Test Categories

### 1. Unit Tests
**Target**: Individual functions and model methods
**Framework**: pytest, pytest-asyncio
**Coverage**: 100% of core business logic

#### User Model Tests
- User creation with valid/invalid data
- Password hashing verification
- Password verification timing
- Profile attribute serialization
- Status transitions

#### Group Model Tests
- Group creation and attributes
- Membership serialization
- System group detection

#### Session Model Tests
- Token generation uniqueness
- Expiration logic
- Revocation behavior
- Activity tracking

### 2. Integration Tests
**Target**: API endpoints and database interactions
**Framework**: pytest, httpx, TestClient

#### Authentication Flow Tests
- POST /api/v1/auth/login with valid credentials → 200, session created
- POST /api/v1/auth/login with invalid credentials → 401
- POST /api/v1/auth/login with locked account → 423
- POST /api/v1/auth/logout → 200
- GET /api/v1/auth/me without session → 401

#### Bootstrap Tests
- POST /api/v1/admin/bootstrap with valid secret key → 200
- POST /api/v1/admin/bootstrap without secret key → 403
- POST /api/v1/admin/bootstrap when admin exists → 409

#### Health Check Tests
- GET /health → 200, {"status": "healthy"}
- GET /docs → 200
- GET /openapi.json → 200

### 3. Security Tests
**Target**: OWASP Top 10 vulnerabilities

#### Authentication Security
- Password verification uses constant-time comparison
- Failed login attempts track correctly
- Account lockout triggers after threshold
- Session tokens are not guessable

#### Input Validation
- Email format validation
- Password length requirements
- SQL injection attempts rejected
- XSS payloads encoded in responses

### 4. Browser Tests (Playwright)
**Target**: End-to-end user journeys
**Framework**: Playwright

#### Admin Journey
1. Navigate to /login
2. Enter valid admin credentials
3. Verify redirected to admin dashboard
4. Verify admin navigation visible
5. Logout
6. Verify redirect to login
7. Attempt to access admin dashboard → redirect to login

#### User Journey
1. Create standard user via API
2. User accesses /login
3. User enters valid credentials
4. Verify redirected to user dashboard
5. Verify admin pages are hidden
6. Logout
7. Verify session invalid

## Test Execution Plan

### Unit Test Commands
```bash
cd backend
pytest tests/ -v --cov=backend --cov-report=html
```

### Integration Test Commands
```bash
cd backend
pytest tests/test_auth.py -v
```

### Browser Test Commands
```bash
cd frontend
npx playwright test
```

### Security Test Commands
```bash
# Run bandit for Python security scanning
bandit -r backend/

# Run npm audit for frontend
npm audit
```

## Acceptance Criteria Verification

| Feature | Test Method | Pass Criteria |
|---------|-------------|---------------|
| Docker Compose starts | Manual | All containers healthy |
| Database migrations | Integration | All tables created |
| Admin bootstrap | Integration | Creates admin user |
| Admin login | Browser | Dashboard accessible |
| End-user login | Browser | User dashboard accessible |
| Authorization | Browser | Admin pages blocked from user |
| User CRUD | Integration | Create/Read/Update/Delete works |
| Group CRUD | Integration | Create/Read/Update/Delete works |
| Audit events | Integration | Events persisted in DB |

## Test Data Requirements
- One admin user with is_super_admin=True
- One standard user with is_admin=False
- Multiple groups for membership testing
- Session tokens for different contexts