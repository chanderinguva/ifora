// Full sign-in: password login -> /oauth/authorize (PKCE) -> /oauth/token. IFORA-59.
//   VUS=20 RAMP=30s DURATION=2m make test-load SCRIPTS=auth_flow
import { sleep } from "k6";
import { FIXTURE, p95, signIn, stages, summary, thresholds, userFor } from "./lib.js";

export const options = {
  stages: stages(),
  thresholds: thresholds({
    // Regression guards, not capacity targets: ~1.5x what 10 VUs measured on a one-worker dev container (README "Load tests").
    step_login: [p95(2500)],      // Argon2id makes login the expensive step on purpose
    step_authorize: [p95(2500)],
    step_token: [p95(3500)],
  }),
};

export default function () {
  signIn(userFor(__VU), "openid profile email");
  sleep(parseFloat(__ENV.THINK_SECONDS || "0.5"));
}

export function handleSummary(data) { return summary("auth_flow", data); }
