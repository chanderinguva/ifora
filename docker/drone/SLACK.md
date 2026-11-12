# Threaded build alerts

The notifier uses Slack Web API and Block Kit: one parent message per build,
updated with recorded phase results/durations and replies for tests, image
publishing, demo deployment and final outcome. Notification errors are ignored
by Drone and cannot block application deployment. No history scopes are needed.

Configure repository secrets (Allow Pull Requests OFF):

- `slack_bot_token`: the Slack app's Bot User OAuth Token (`xoxb-…`), with `chat:write`.
- `slack_channel_id`: the channel ID, with the bot invited to that channel.

After adding scopes, reinstall the Slack app. Existing `slack_webhook` is unused
by the new pipeline; retain it until the bot integration is verified, then remove
it if no other integration needs it. Never put credentials in source or logs.

`scripts/ci-record.sh` records phase outcomes and elapsed seconds under
`.ci/results`; `scripts/ci-slack.py` stores only channel, message timestamp and
delivered events under `.ci/slack`. No token is persisted. Successive notification
steps are ordered to avoid competing parent updates. Application steps do not
depend on notification completion. Network retries are bounded; exactly-once
delivery cannot be guaranteed after ambiguous network failures.

Thread identity uses repository and build number only. Start timestamps and stage
metadata are excluded because their values can differ between notification steps.
Missing build identity fails the notification before contacting Slack.
This change applies to future builds; it does not consolidate existing duplicate
messages or change a pipeline already running an older commit.

The parent may first appear at a later milestone if the start notification fails.
Missing phase data is shown as unreported, never guessed successful. An overall
failure can leave demo deployed while dev failed; the message explicitly warns
about partial deployment and no automatic rollback.

This is best-effort pipeline reporting, not an external outage monitor. It cannot
cover every clone failure, cancellation, runner outage, missed GitHub webhook or
offline host. Real Slack delivery and rendering must be verified on the next run.
