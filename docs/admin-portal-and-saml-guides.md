# Admin portal, SAML guides and unified provisioning

## User dashboard alongside Admin

The admin sidebar has an End-user dashboard link, also available on the
collapsed rail and mobile drawer. It opens /dashboard in a separate tab.
Personal routes (/dashboard, /apps and children, /settings) use end-user
navigation without calling either role-switch endpoint. The account is the
administrator's own account; API assignment and authorization checks still apply.
This is not impersonation or a reduced-privilege session. The existing explicit
Switch to user view operation remains separate.

## SAML instructions and draft translator

Applications > application > Sign On > View setup instructions offers Slack
and generic instructions. Values come from saved server configuration. Copy
buttons are blocked while there are unsaved changes. A certificate is available
after configuration is saved. Official links and review dates accompany Slack's
guide; adding vendors extends frontend/src/lib/saml-guides.ts.

Describe your SAML configuration is a local sentence parser, not a general AI
assistant. It supports explicit ACS, SP entity ID, audience, Name ID, signing,
user-attribute and filtered group-claim instructions shown in its examples.
Unrecognized/conflicting instructions block applying. Review the proposal,
apply to the draft, then save through the existing validated API. Neither this
parser nor guide selection saves, enables provisioning or contacts an external
model. Existing unrelated claim mappings are retained. A changed form makes an
old proposal inapplicable until reviewed again.

## One application for SAML and SCIM

The existing Provisioning tab now creates a provisioning facet with the current
application_id rather than a second application. Existing SSO and assignments
remain in place. The embedded editor reuses the existing provisioning management
component for testing, credentials, behavior, mappings, resources and activity.
Read-only administrators cannot edit the connection.

The connection starts disabled; credentials are password fields, sent only
to the existing API, encrypted server-side and not read back. Testing is
required by the backend before enabling. Enabling can synchronize existing
assignments. All SAML applications expose provisioning setup, but the service
must support SCIM 2.0 and any vendor-plan requirements.

The optional Slack helper uses https://api.slack.com/scim/v2 and bearer
authentication. Slack requires an authorized OAuth admin-scope credential;
the messaging bot token is not a substitute. See
https://docs.slack.dev/admins/scim-api/.

Enabled SCIM configurations show a Push Groups tab. It uses the existing
shared group assignments and backend group-push behavior. Saving that behavior
requires confirmation and can queue a full sync including users. Group result
rows come from the current linked-resource page, not a full remote inventory.

Inbound Import is not implemented by this change. It requires a separate,
reviewed preview/matching/confirmation flow before creating local users or links.
No nonfunctional Import tab is presented as an available capability.

## Role labels

The user list returns administrator-role display metadata in two batched queries
per nonempty page, combining direct and group-derived assignments. The UI displays
canonical role names, multiple roles and source tooltips. An admin flag without a
role is not labeled an organization administrator. This changes no authorization.

## Verification

Run from frontend:

    npm run test:unit
    npm run build

Run from the repository:

    python -m unittest discover -s scripts/tests -p test_role_serialization.py -v

The normal backend integration suite includes test_user_list_role_labels.py.
Drone's frontend check also runs the new unit suite.

Before merging/deploying, verify in a disposable tenant:

1. Open the personal dashboard from Admin and confirm the admin tab remains
   operational, unsaved input is preserved, and the new tab lists only assigned apps.
2. Review saved Slack instructions and copy exact values; change a form field
   and confirm copying requires saving. Test unsupported translator input.
3. Add SCIM on the SAML application's Provisioning tab; confirm only one
   Application exists, provisioning stays off, and credentials remain masked.
4. Test with a vendor test account, inspect mappings, then explicitly enable.
   Check shared group assignments and group-push behavior only in that test tenant.
5. Verify direct and group-derived organization/application roles in Users,
   including multiple roles, a super administrator and a roleless administrator.

Local SSR/unit checks do not establish browser layout, live Slack delivery,
SCIM compatibility or successful database integration.
