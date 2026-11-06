# ADR-002: Session Management

## Status
Accepted

## Context
We need to implement secure user session management that prevents session hijacking, fixation, and other attacks while providing a good user experience.

## Decision
Use server-side session storage with cryptographically secure opaque tokens.

### Implementation Details

#### Session Token Generation
- Algorithm: secrets.token_urlsafe(32)
- Entropy: 256 bits
- Format: URL-safe Base64 encoded

#### Session Lifecycle
1. **Creation**: On successful authentication
2. **Rotation**: After authentication and privilege change
3. **Invalidation**: On explicit logout and expiration
4. **Expiration**: Configurable (default 8 hours)

#### Storage
- Primary: PostgreSQL database with foreign key to users table
- Cache: Redis for session validation (optional optimization)

#### Security Headers
- Set-Cookie: HttpOnly, Secure (in production), SameSite=Lax
- Path=/ for all session endpoints

## Database Schema
```sql
CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token VARCHAR(64) UNIQUE NOT NULL,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    last_activity_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    is_admin_session BOOLEAN DEFAULT false
);
```

## Alternatives Considered
- Client-side JWT tokens: Cannot be revoked without additional infrastructure
- Stateful sessions in memory: Not scalable, lost on restart
- OAuth-style access/refresh tokens: Complex for simple internal use case

## Consequences
- Session lookup requires database query (mitigated by Redis cache)
- Need to clean up expired sessions (can be done via scheduled job)
- Provides full audit trail of session activity

## Security Considerations
- Token is never stored in plaintext in logs
- IP address and user agent tracked for audit
- Session revocation possible via DELETE endpoint