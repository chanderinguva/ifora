## Story
Jira: IFORA-___ (parent epic: IFORA-___)

## What changed and why
<!-- Two or three sentences. Link the acceptance criteria this satisfies. -->

## Verification (required)
<!-- There is no hosted CI. Paste the real output; do not claim a gate passed unless you ran it. -->

`make check` output (or `make check-fast` plus the specific tests you ran):

```
paste here
```

- [ ] Every acceptance criterion has a test, or is listed under "Not verified" below
- [ ] New or changed security behaviour has a test that fails on the old code
- [ ] No secrets, tokens or real personal data in the diff, tests or logs
- [ ] No GitHub Actions workflow added (`.github/workflows` stays empty)
- [ ] Migrations (if any) have a tested downgrade
- [ ] README updated if the change is user-facing

## Not verified / known gaps
<!-- Be explicit. Skipped gates, environment-only failures, follow-ups. -->

## Rollback
<!-- Usually: revert this PR. Say if a migration or config change needs more. -->

Do not merge until a human has reviewed.
