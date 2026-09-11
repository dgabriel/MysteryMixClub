# Security Policy

## Reporting a vulnerability

If you find a security vulnerability in MysteryMixClub, please report it
privately rather than opening a public issue:

- Use [GitHub's private vulnerability reporting](../../security/advisories/new)
  for this repository, or
- Email dgabriel@gmail.com with details.

Please include steps to reproduce, the affected component, and (if known)
potential impact. We'll acknowledge reports as quickly as we can and follow
up once the issue is understood.

## Supported versions

This project runs as a single deployed instance rather than shipping
versioned releases — only the current `main` branch is supported. There is
no backport policy for older commits.

## Scope

In scope: the application code in `frontend/` and `backend/`, and the CI/CD
configuration in `.github/workflows/`. Out of scope: third-party dependencies
(report those upstream) and the hosting infrastructure itself.
