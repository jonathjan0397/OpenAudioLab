# Security

## First-Run Setup

- No default production credentials
- Setup required before public usage
- Passwords hashed with bcrypt (12 rounds)
- Minimum 12 characters, rejects common placeholders

## Authentication

- JWT-based authentication
- Token stored in localStorage (frontend)
- Protected routes require valid token
- Admin-only routes for settings management

## Worker Security

- Registration requires `WORKER_REGISTRATION_TOKEN`
- Workers receive unique `worker_api_token` after registration
- No anonymous worker polling

## Storage Security

- Generated files are private by default
- No public directory browsing
- Signed download URLs with expiration
- Default 7-day retention

## Production Warnings

Backend warns or fails if:
- SECRET_KEY is default
- JWT_SECRET is default
- WORKER_REGISTRATION_TOKEN is default
- Storage credentials missing for cloud storage
- Setup incomplete and app is publicly exposed
