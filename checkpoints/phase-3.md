# Checkpoint — Phase 3: Auth + Onboarding

**Completed:** 2026-09-04
**Goal:** registration, sign-in, Google auth, session verification, onboarding, profile,
recruiting consent, and account data controls — followed by a security review.

---

## What was built

### Backend

| Area | Delivered |
|---|---|
| Password auth | Argon2id hashing, transparent rehash on login as parameters harden |
| Sessions | HS256 access JWT (15 min) + opaque refresh token (30 d), both `HttpOnly` cookies |
| Rotation | Refresh rotates on every use; reuse revokes the whole rotation family |
| Google | ID-token verification against Google's JWKS; no client secret stored |
| Rate limiting | Two Redis buckets — loose per-IP, tight per-account |
| Onboarding | School, graduation year, target role; idempotent |
| Consent | Dedicated endpoint, default off, timestamped, revocable |
| Data controls | Full JSON export; permanent deletion with password + phrase confirmation |
| Schema | `refresh_tokens` table with hash, family, expiry and revocation |

### Frontend

Sign-up, sign-in, onboarding, dashboard and account pages; app shell with sidebar navigation;
`src/proxy.ts` for silent session refresh and route gating; typed API client that forwards
cookies from Server Components; `Field`, `Input`, `Select`, `Alert` primitives.

---

## Verification

### Automated

```
backend  pytest                 143 passed
backend  pytest (no infra)      31 passed, 112 skipped   (skip guards intact)
backend  ruff check / format    All checks passed / 76 files formatted
backend  mypy core commons      Success: no issues found in 61 source files
web      eslint / tsc / vitest  clean / clean / 9 passed
web      next build             Compiled successfully, 8 routes
```

### Manual, against the running stack

Registration → onboarding → dashboard → account was driven end to end in a real browser. The
signed-in shell, pre-populated profile, consent control and deletion section all render, the
Continue button is correctly disabled until onboarding is complete, and the browser console
carries no application errors or hydration warnings.

Verified over HTTP:

```
register                      201, two HttpOnly cookies set, consent false
GET /auth/me   (cookies)      200
GET /auth/me   (none)         401
GET /auth/me   (forged)       401
onboarding                    saved; consent still false
consent grant                 true + timestamp recorded
consent withdraw              false
profile PATCH with consent    school changed, consent unchanged
refresh                       token value differs -> rotated
replay of rotated token       401
next token after detection    401  (whole family revoked)
logout                        subsequent refresh 401
deletion: wrong phrase        422
deletion: wrong password      401
deletion: missing password    400
deletion: correct             200; /auth/me 401; login 401
Google (unconfigured)         503, not an internal error
route gating /dashboard       307 -> /signin?next=%2Fdashboard
```

### Security review

| Check | Result |
|---|---|
| Secrets committed | `.env` not staged; no `JWT_SECRET` in tracked files |
| Secret material in logs | None — token log lines carry user IDs and outcomes only |
| Credential fields in responses | `CurrentUserResponse` is `id, email, is_admin, email_verified, onboarding_complete, profile` |
| Client-supplied user IDs | **0 routes** accept one — no IDOR surface |
| Unauthenticated routes | Exactly register, login, google, refresh, logout; every account route requires auth |
| CORS | No `Access-Control-Allow-Origin` returned even for a hostile `Origin` — same-origin only |
| Cookie attributes | `HttpOnly; Max-Age; Path=/; SameSite=lax`; `Secure` gated on environment and unit-tested |
| API docs | Disabled when `ENVIRONMENT=production` |
| Admin gate | Returns **404**, not 403, so admin endpoints are not confirmed to exist |
| Account enumeration | Identical body and status for unknown vs. wrong password |
| Timing side channel | Measured: **0.8 ms** median difference (see below) |

---

## Problems found and fixed

1. **An apparent 114 ms timing leak that was my own measurement error.** The first run showed
   unknown accounts failing far faster than known ones. The cause was the rate limiter returning
   429 instantly once the budget was spent, not a missing constant-time path. Re-measured with
   counters cleared and the two cases interleaved: **0.8 ms** difference. The dummy-hash defence
   works. Worth recording because the wrong conclusion here would have been a fabricated
   vulnerability *and* a fabricated fix.

2. **Per-IP-only rate limiting was wrong for this product.** The users are university students
   who overwhelmingly share campus NAT addresses, so 10 attempts per 15 minutes per IP would have
   locked out an entire university the moment a few people mistyped a password. Split into a
   loose per-IP bucket (60) and a tight per-account bucket (8). Verified: one account locks after
   8 attempts while a different account from the same address still signs in.

3. **Rate-limit state leaked between tests.** The suite passed file-by-file and failed as a whole,
   because 111 tests share one apparent client address and exhausted the registration budget.
   Counters are now cleared per test. This was a real bug in the harness, not a flake to retry.

4. **Next 16 deprecates `middleware.ts`.** Migrated to `proxy.ts` with the official codemod rather
   than shipping a deprecated convention in new code.

5. **Authenticated pages failed the production build**, because Next tried to prerender them and
   the build has no session or reachable API. The cookie read sits behind a dynamic
   `import('next/headers')` that static analysis cannot see, so the pages are now explicitly
   `force-dynamic`.

6. **`typedRoutes` rejected runtime-built redirect targets**; typed with `as Route`.

7. **Two pieces of my own sloppiness**: a leftover no-op expression in `verify_password`, and
   `hasPassword={!user.is_admin || true}` — an always-true condition. Both removed.

---

## Design decisions

**Access tokens carry no authorisation claims.** Only `sub`, `typ`, `iat`, `exp`, `jti`. Admin
rights and account status are read from the database on every request. That is one indexed
primary-key lookup per request, deliberately preferred over a 15-minute window in which a
suspended account keeps working.

**Refresh tokens are opaque and stored, not JWTs.** A session must be revocable on sign-out,
password change, or theft detection, and a signature cannot be taken back. Stored as SHA-256
rather than Argon2: the value is 384 bits of server-generated randomness, so it needs no
key-stretching, and refresh is frequent enough that a deliberately slow hash would be a real
latency cost.

**Consent has its own endpoint and its own schema.** `PATCH /v1/profile` strips
`recruiting_consent` server-side, so consent can never ride along with an unrelated save. Tested
directly.

**Deletion is a real delete.** The user row is removed and the foreign keys cascade to profile,
sessions, attempts, grades and mastery. A soft-delete flag would have been easier and would not
have honoured the request.

---

## Honest scope statement

- **Google sign-in is implemented but has never run against Google.** There is no
  `GOOGLE_CLIENT_ID` available, so the verification path — JWKS fetch, signature, issuer and
  audience checks — is covered only by the unconfigured-service tests. It is **not** verified
  against a live Google token.
- **No email verification flow.** `email_verified_at` is set for Google sign-ups and stays null
  for password sign-ups. Sending a verification email belongs with the rest of transactional
  email in Phase 10.
- **No password reset.** It needs the same email infrastructure. A user who forgets their
  password currently has no self-service route.
- **The dashboard is a placeholder** that says so plainly rather than rendering empty charts.
- **`grade_flags` in the export is always an empty list** — the flag API does not exist yet.
- **No frontend tests for the new forms.** Only the two Phase 1 suites run. The auth flows are
  covered by 143 backend tests and the manual browser pass, not by component tests.
- **No E2E suite.** Playwright is still unconfigured.

---

## Blockers

None.

---

## Next

**Phase 4 — Question bank + admin.** Question and version APIs, rubric completeness validation,
admin question management, activation and retirement, version history — and the tests that prove
ideal answers and rubrics never reach a client before submission.
