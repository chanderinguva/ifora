# IdentityForge Security Threat Model

## Overview
This document outlines the security threats, mitigations, and considerations for the IdentityForge Identity and Access Management platform.

## Asset Inventory

| Asset | Description | Sensitivity |
|-------|-------------|-------------|
| User Credentials | Email, password hash, profile data | High |
| Session Tokens | Opaque session identifiers | High |
| Audit Logs | Authentication and admin actions | Medium |
| API Keys | Future connector keys | High |

## Threat Categories

### 1. Authentication Threats

#### Threat: Brute Force Password Attack
- **Description**: Attackers attempt to guess passwords through repeated login attempts
- **Mitigation**: Implemented failed login tracking, account lockout after 5 attempts, configurable lockout duration

#### Threat: Credential Stuffing
- **Description**: Attackers use leaked credentials from other sites
- **Mitigation**: Argon2id password hashing prevents hash lookup, rate limiting

#### Threat: Session Hijacking
- **Description**: Attackers steal session tokens and impersonate users
- **Mitigation**: HttpOnly, Secure, SameSite cookies; server-side session storage; token regeneration

### 2. Authorization Threats

#### Threat: Insecure Direct Object Reference (IDOR)
- **Description**: Users access other users' data by manipulating IDs
- **Mitigation**: Object-level authorization checks, deny-by-default policy

#### Threat: Privilege Escalation
- **Description**: Regular users gain admin privileges
- **Mitigation**: Role-based access control, separate admin secret for bootstrap

### 3. Data Threats

#### Threat: Broken Authentication
- **Description**: Session tokens or credentials exposed
- **Mitigation**: Secure cookie flags, HTTPS enforcement, CSRF protection

#### Threat: Sensitive Data Exposure
- **Description**: Passwords, tokens leaked in logs or response
- **Mitigation**: Never log credentials, sanitized audit events

### 4. Input Validation Threats

#### Threat: SQL Injection
- **Description**: Malicious SQL in user input
- **Mitigation**: SQLAlchemy ORM with parameterized queries

#### Threat: Cross-Site Scripting (XSS)
- **Description**: Malicious scripts in user input
- **Mitigation**: Input validation with Zod, React auto-escaping

#### Threat: Cross-Site Request Forgery (CSRF)
- **Description**: Unauthorized actions from authenticated users
- **Mitigation**: SameSite cookie policy, CSRF tokens (future)

## Security Controls

### Implemented
- Argon2id password hashing
- Cryptographically secure session tokens (256 bits)
- Server-side session storage
- Secure cookie attributes (HttpOnly, SameSite)
- Login throttling and account lockout
- Audit logging for sensitive actions
- Deny-by-default authorization
- Input validation with Zod/pydantic

### Planned
- CSRF token implementation
- Rate limiting at infrastructure level
- Security headers (CSP, HSTS)
- MFA implementation
- Session invalidation across devices

## Attack Surface Analysis

### Network
- Database exposed only to application containers
- Redis cache not exposed externally
- API behind reverse proxy (future)

### Code
- No secrets in source code
- Environment-based configuration
- Dependency scanning with safety/pip-audit

### Physical
- Docker volumes for data persistence
- No persistent logs on host (future: centralized logging)

## Compliance Considerations
- OWASP Top 10 compliance
- GDPR data handling (right to deletion)
- SOC 2 audit trail requirements

## Incident Response
1. Session hijacking detected → invalidate session, notify user
2. Brute force attack detected → alert admin, block IP temporarily
3. Data breach suspected → audit logs, change all secrets