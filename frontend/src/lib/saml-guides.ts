export type SamlGuide = {
  id: string; name: string; reviewed: string;
  prerequisites: string[]; steps: string[]; troubleshooting: string[];
  sources: { label: string; url: string }[];
};

/** Reviewed content, not executable configuration. Add vendor guides here. */
export const SAML_GUIDES: SamlGuide[] = [
  {
    id: "generic", name: "Custom SAML application", reviewed: "2026-11-13",
    prerequisites: ["An application that accepts SAML 2.0 and an account permitted to manage its SSO settings."],
    steps: [
      "Obtain the application's ACS URL and SP entity ID from its SSO settings or metadata. Enter those in Ifora and review its required attributes and Name ID format.",
      "Save the SAML settings. Copy the saved Ifora identity-provider values below into the application's SSO configuration, or import Ifora metadata if supported.",
      "Assign a test user or group under Assignments. Use Preview in Ifora to inspect attributes; preview does not perform a real login.",
      "Keep an existing application administrator session open. Test from the application's sign-in page and from the assigned user's My apps tile before requiring SSO.",
    ],
    troubleshooting: ["Check exact issuer, audience and ACS values on both sides. Verify signing certificate, attribute names and user assignment. Consult the application's documentation for binding and certificate requirements."],
    sources: [],
  },
  {
    id: "slack", name: "Slack", reviewed: "2026-11-13",
    prerequisites: ["A Slack owner account with access to SAML settings; check your plan's eligibility. Keep an owner recovery sign-in available."],
    steps: [
      "In Ifora use your Slack workspace's /sso/saml endpoint as ACS, https://slack.com as SP entity ID, persistent Name ID, and signed responses. Add required User.Email mapped to email.",
      "Save in Ifora, then open Slack's SSO & authentication settings and Configure SAML.",
      "Copy the saved endpoint, issuer and certificate below into Slack. Set its Service Provider Issuer to the same SP entity ID as Ifora. Use HTTP POST binding.",
      "Assign a test user whose email matches Slack. Run Slack Test Configuration, then test the My apps tile. Name the provider Ifora for the sign-in button.",
    ],
    troubleshooting: ["Check User.Email, persistent Name ID, signed response, certificate and matching ACS/audience values. Use Slack's diagnostic error before changing settings."],
    sources: [
      { label: "Slack custom SAML requirements", url: "https://slack.com/help/articles/205168057-Custom-SAML-single-sign-on" },
      { label: "Slack SSO setup and prerequisites", url: "https://slack.com/help/articles/203772216-Set-up-SAML-single-sign-on-for-Slack" },
      { label: "Slack SAML troubleshooting", url: "https://slack.com/help/articles/360037402653-Troubleshoot-SAML-authorization-errors" },
    ],
  },
];

export function suggestedSamlGuide(spEntityId: string, acsUrl: string): string {
  try {
    const acs = new URL(acsUrl);
    if (acs.protocol === "https:" && acs.hostname.endsWith(".slack.com") && acs.pathname === "/sso/saml") return "slack";
  } catch { /* incomplete or custom URL: show generic instructions */ }
  return spEntityId === "https://slack.com" ? "slack" : "generic";
}
