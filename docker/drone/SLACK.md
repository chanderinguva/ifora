# Slack build and deployment alerts

The pipeline uses the official `plugins/slack` incoming-webhook integration.
Its image is pinned to a verified multi-architecture digest including arm64.

## One-time setup

1. At https://api.slack.com/apps create an app in the workspace where you want
   alerts. Enable **Incoming Webhooks**, then **Add New Webhook to Workspace**.
2. Select the alerts channel. For a private channel, make sure your account can
   access it and authorize the app for that channel.
3. Copy the webhook URL directly into Drone: repository **Settings → Secrets**,
   name **`slack_webhook`**. Leave **Allow Pull Requests** unchecked.
   Keep the URL out of Git, terminal logs, screenshots and chat.
4. Merge the pipeline change; the next main-branch push uses the secret.

The webhook determines the destination channel. The pipeline does not override
the channel, app name or icon; configure these in Slack instead. No Slack bot
token or separate channel secret is needed.

## Messages

| Event | Message |
| --- | --- |
| Tests and image publishing pass | Build ready; deployments starting |
| Demo health checks pass | Demo deployed; dev/prod next |
| Entire pipeline passes | Both environments deployed and healthy |
| A pipeline step fails | Failure with a build link; deployments may be partial |

All messages include a link to the Drone build. Notifications run independently
of the deployment dependency chain, so delivery order can vary. They use
`failure: ignore`: missing/invalid webhook configuration or Slack delivery errors
must not turn a successful application build into a failed deployment. Review
the Slack step logs when messages do not arrive.

This is best-effort notification from a running pipeline, not an external
availability monitor. It cannot report a webhook that never reached Drone, a
runner that cannot start, every early clone failure, cancellation, or a host
that sleeps or loses connectivity. A failure alert does not imply rollback.

Validation of real message delivery requires adding the secret and running the
pipeline. No test messages are sent by this repository change.
