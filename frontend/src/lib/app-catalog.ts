/**
 * Starter catalog for the Create app integration wizard. Entries are bookmarks to each vendor's public sign-in page:
 * they pre-fill a name and URL, nothing more. SAML/OIDC values are tenant-specific, so they are never guessed here.
 * No vendor logos are bundled (trademark); upload one on the application page.
 */
export type CatalogEntry = { id: string; name: string; category: string; url: string };

export const CATALOG: CatalogEntry[] = [
  { id: "github", name: "GitHub", category: "Developer", url: "https://github.com/login" },
  { id: "gitlab", name: "GitLab", category: "Developer", url: "https://gitlab.com/users/sign_in" },
  { id: "slack", name: "Slack", category: "Collaboration", url: "https://slack.com/signin" },
  { id: "zoom", name: "Zoom", category: "Collaboration", url: "https://zoom.us/signin" },
  { id: "notion", name: "Notion", category: "Collaboration", url: "https://www.notion.so/login" },
  { id: "atlassian", name: "Atlassian (Jira, Confluence)", category: "Collaboration", url: "https://id.atlassian.com/login" },
  { id: "google", name: "Google Workspace", category: "Productivity", url: "https://accounts.google.com/" },
  { id: "m365", name: "Microsoft 365", category: "Productivity", url: "https://www.office.com/" },
  { id: "dropbox", name: "Dropbox", category: "Productivity", url: "https://www.dropbox.com/login" },
  { id: "box", name: "Box", category: "Productivity", url: "https://account.box.com/login" },
  { id: "salesforce", name: "Salesforce", category: "CRM", url: "https://login.salesforce.com/" },
  { id: "hubspot", name: "HubSpot", category: "CRM", url: "https://app.hubspot.com/login" },
  { id: "figma", name: "Figma", category: "Design", url: "https://www.figma.com/login" },
  { id: "aws", name: "AWS Console", category: "Cloud", url: "https://console.aws.amazon.com/" },
  { id: "gcp", name: "Google Cloud Console", category: "Cloud", url: "https://console.cloud.google.com/" },
  { id: "azure", name: "Azure Portal", category: "Cloud", url: "https://portal.azure.com/" },
];
