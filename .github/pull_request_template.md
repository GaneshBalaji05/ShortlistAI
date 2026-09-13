## What changed?

Describe the smallest necessary change.

## Why did it break?

**Root cause:**

Explain the actual cause, not only the visible symptom.

## How was it reproduced?

Include the input/state/device/route/data condition that demonstrated the bug.

## Support added with the fix

- [ ] Regression test/check for the original bug
- [ ] Negative/boundary case coverage
- [ ] Useful diagnostics/logging where needed
- [ ] User-facing fallback/error handling where needed
- [ ] Safe/idempotent migration where needed
- [ ] PWA/cache/update handling where needed
- [ ] Security/workspace isolation reviewed

## Regression review

List nearby flows tested and any known-good behavior that must remain unchanged.

## Production verification

- [ ] CI/checks passed
- [ ] Exact commit deployed
- [ ] Production flow tested end-to-end
- [ ] Production logs checked after testing
- [ ] Rollback/recovery path understood

**Production evidence:**

Do not mark the PR/bug complete only because code merged or a deployment became live. Follow `BUG_FIX_STANDARD.md`.
