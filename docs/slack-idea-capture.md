# Slack message shortcut: Send to Ifora

The internal Slack app adds **Send to Ifora** to a message's overflow menu. Selecting it stores a durable delivery job, acknowledges Slack immediately, and creates one Discovery idea for that Slack message. Slack retries and repeated selections are deduplicated by workspace, channel and message timestamp.

The captured idea includes the message text, author context, channel, permalink and attachment metadata. The permalink remains the source of truth for attachment content because Slack file URLs require Slack authentication.

## Public endpoint

Slack must reach `POST /api/v1/integrations/slack/idea-shortcut` without an interactive Cloudflare Access login. Expose only that exact path through the tunnel or a dedicated `hooks.ifora.app` hostname. The route authenticates every request with Slack's timestamped HMAC signature, restricts the workspace and restricts users. Keep the rest of the API behind the current access policy.

## Configuration

Generate independent random values for the Discovery ingestion token and configure the same ingestion token in Ifora Discovery and the Ifora backend. Keep all values outside Git.

Required backend settings:

```text
SLACK_IDEA_CAPTURE_ENABLED=true
SLACK_IDEA_SIGNING_SECRET=<Slack Basic Information > App Credentials > Signing Secret>
SLACK_IDEA_ALLOWED_TEAM_ID=<workspace team ID>
SLACK_IDEA_ALLOWED_USER_IDS=<comma-separated Slack user IDs>
IFORA_DISCOVERY_INGEST_URL=https://ifora-discovery-hub.chander-inguva.chatgpt.site/api/integrations/slack
IFORA_DISCOVERY_INGEST_TOKEN=<shared random token>
IFORA_DISCOVERY_SITES_AUTH_TOKEN=<private Site service-access token>
```

Required Discovery Site settings:

```text
IFORA_DISCOVERY_INGEST_TOKEN=<same shared random token>
IFORA_DISCOVERY_OWNER_ID=<the Site owner's stable authenticated user ID>
```

## Slack app manifest

Replace the request URL with the public signed endpoint, then create an app from this manifest and install it to the Ifora workspace:

```yaml
display_information:
  name: Ifora Discovery
  description: Capture product ideas from Slack messages
  background_color: "#4f46e5"
features:
  shortcuts:
    - name: Send to Ifora
      type: message
      callback_id: send_to_ifora
      description: Capture this message as an Ifora Discovery idea
oauth_config:
  scopes:
    bot: []
settings:
  interactivity:
    is_enabled: true
    request_url: https://hooks.ifora.app/api/v1/integrations/slack/idea-shortcut
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

No bot OAuth scopes are required for the shortcut. After installation, copy the signing secret and workspace/user IDs into the deployment settings, apply migration `0057`, and restart the API and recipes worker. The worker retries failed Discovery deliveries with exponential backoff.

