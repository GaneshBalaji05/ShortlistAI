# ShortlistAI Bug Fix Standard

Every bug fix must solve the immediate symptom **and** add the support needed to stop the same class of failure from returning.

## Required for every bug

1. **Reproduce first**
   - Confirm the failure with real inputs or production evidence before changing code.
   - Record the affected route, UI state, data condition, device/browser, or workflow.

2. **Fix the root cause**
   - Do not patch only the visible symptom.
   - Inspect adjacent code paths, runtime patches, data migrations, caching, authentication, workspace isolation, and deployment behavior where relevant.

3. **Add regression protection**
   - Add or update an automated test/check that fails on the original bug.
   - Test important boundary cases, not only the happy path.
   - For search bugs, include false-positive and false-negative examples.
   - For auth bugs, test session creation, expiry, logout, redirects, and workspace isolation.
   - For PWA/mobile bugs, test cache/update behavior and mobile + desktop modes.

4. **Add operational support**
   - Add useful server/client logging where a future failure would otherwise be invisible.
   - Return clear user-facing errors without leaking secrets or internal details.
   - Add safe fallback/recovery behavior when appropriate (retry, cache recovery, migration fallback, idempotency, etc.).

5. **Protect data and security**
   - Verify workspace/tenant scoping for every read and write touched by the fix.
   - Never log passwords, session tokens, reset tokens, API keys, or private candidate data unnecessarily.
   - Database/schema fixes must be backward-compatible and idempotent.

6. **Verify surrounding behavior**
   - Re-test the feature that broke plus nearby critical flows so the fix does not create a regression elsewhere.
   - Preserve known-good behavior unless the requirement explicitly changes it.

7. **Verify production**
   - A merge or successful build is not completion.
   - Confirm the exact deployed commit.
   - Confirm the affected production route/flow works after deployment.
   - Check production logs for errors immediately after verification.

8. **Have a recovery path**
   - Prefer changes that can be safely rolled back.
   - For risky data/schema changes, define what happens if deployment partially fails.
   - For browser/PWA state, include a version/cache migration strategy when needed.

## Definition of Done

A bug is only complete when all applicable items below are true:

- [ ] Original bug reproduced or supported by production evidence
- [ ] Root cause identified
- [ ] Root-cause fix implemented
- [ ] Regression test/check added
- [ ] Boundary/negative case tested
- [ ] Logging/diagnostics sufficient for future failures
- [ ] User-facing fallback/error handling added where needed
- [ ] Security and workspace isolation reviewed
- [ ] Mobile/PWA/cache behavior reviewed where applicable
- [ ] Database migration is safe/idempotent where applicable
- [ ] Nearby critical flows regression-tested
- [ ] Exact commit deployed
- [ ] Production flow verified
- [ ] Production logs checked
- [ ] Rollback/recovery path understood

## ShortlistAI-specific critical regression areas

When a fix touches any shared runtime or global UI code, also consider these critical flows:

- Login, Create Account, Forgot Password, session/logout
- Workspace isolation for candidates, jobs, notes, activity and interviews
- Talent Pool Boolean search (Java must not match JavaScript)
- Candidate duplicate merge by email/phone/LinkedIn
- Scoring stability and explainability
- Role-specific pipeline counts/stages
- Bulk ingestion persistence/searchability
- PWA install/update/cache behavior
- Mobile/Desktop manual view switching
- Interview scheduling/calendar behavior

Do not mark a bug complete solely because the code exists or Render says the deploy is live. The user-visible production behavior is the final verification point.
