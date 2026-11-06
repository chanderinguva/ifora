# ADR-001: Password Hashing Algorithm

## Status
Accepted

## Context
We need to store user passwords securely while resisting modern attacks including GPU/ASIC cracking. The system must comply with OWASP password guidelines.

## Decision
Use Argon2id for password hashing.

### Implementation Details
- Algorithm: Argon2id (hybrid of Argon2i and Argon2d)
- Parameters: Default recommended by passlib
- Memory cost: 65536 KB
- Time cost: 2 iterations
- Parallelism: 4 threads

### Why Argon2id
1. **Memory-hard**: Resistant to GPU/ASIC attacks
2. **Standardized**: Winner of PHC (Password Hashing Competition)
3. **Hybrid protection**: Argon2i for side-channel resistance, Argon2d for GPU resistance
4. **Widely supported**: Python passlib implementation

## Alternatives Considered
- bcrypt: Good, but less resistant to GPU attacks than Argon2id
- scrypt: Good, but more complex parameter tuning
- PBKDF2: Not memory-hard, vulnerable to GPU attacks

## Consequences
- Requires passlib[argon2] dependency
- Password verification slightly slower than plaintext comparison
- Industry standard for secure password storage

## References
- OWASP Password Storage Cheat Sheet
- RFC 9106: Argon2 Password Hashing