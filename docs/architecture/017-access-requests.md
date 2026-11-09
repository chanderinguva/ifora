# ADR 017: Self-service access requests

Status: accepted (phase 10 of `docs/project/okta-parity-roadmap.md`)

## Decision
- An administrator switches **Self service** on per application (General tab; optional "reason required"). Table `application_self_service`; absent row = off.
- Users see requestable apps they do not already have under **Request access** and ask with an optional/required reason (`access_requests`, status pending → approved | denied | canceled).
- An administrator with the *applications* area (org admin, app admin; read-only roles cannot decide) approves or denies under **Access requests**. Approval creates an ordinary direct `application_assignments` row and runs the same provisioning hook as a manual assignment, so entitlement, SCIM/provisioning and audit behave identically.
- Audit: `ACCESS_REQUESTED`, `ACCESS_REQUEST_APPROVED/DENIED/CANCELED`, `APPLICATION_SELF_SERVICE_CHANGED`, plus the usual `APPLICATION_ASSIGNMENT_ADDED` (tagged `via: access_request`). The admin dashboard gets a Task for pending requests.

## Security properties
- Asking grants nothing: tiles, launch, OIDC/SAML/SWA all still require an assignment.
- An app that is missing, inactive, hidden, provisioning-only or not self-service answers 404 to a request, so request ids and app existence are not probed.
- One pending request per user and app (partial unique index); at most 20 pending per user.
- Decisions lock the row (`FOR UPDATE`) and are single-use (409 afterwards). A pending request canceled by the user cannot then be approved.
- Separation of duties: nobody decides their own request, including super admins.
- Approval refuses when the user is not active or the app is inactive; no assignment is created in that case.
- Users only see and cancel their own requests; another person's id gets 404.
- Reasons and notes are plain text (≤500 chars, control characters rejected) and rendered as text.

## Not done
Email notification of requesters/approvers, per-app approver groups, multi-step approval, time-limited access, request via group assignment, bulk decisions.
