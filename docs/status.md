# TG Outreach Minimal Accounts Status

## Current Phase
- In progress: final validation, commit, push, deploy.

## Done
- Account public payload flattened to simple status fields.
- Nested diagnostic account payload removed from Accounts API/UI.
- `/api/accounts/{id}/health` removed.
- Warming backend router removed.
- Warming worker removed.
- Warming frontend page, navigation, and API client methods removed.
- Warming ORM models and bootstrap columns removed.
- Campaign account picker now uses direct `account.can_receive`.

## Validation Completed
- Backend compile passed.
- Runtime test file passed.
- Frontend build passed.

## Next
- Run final search gate.
- Commit and push.
- Deploy Railway.
- Verify `/api/accounts/` returns direct status fields and no nested diagnostic payload.
