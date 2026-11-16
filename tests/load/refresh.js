// Refresh-token rotation. Each VU signs in once (not measured here), then rotates its token for the whole run:
// every rotation returns a new token and kills the old one, so a VU must chain, never reuse. IFORA-59.
import { sleep } from "k6";
import { FIXTURE, exchange, p95, signIn, stages, summary, thresholds, userFor } from "./lib.js";

export const options = {
  stages: stages(),
  // Regression guard from the 10 VU baseline on a one-worker dev container, not a capacity target.
  thresholds: thresholds({ step_refresh: [p95(3500)] }),
};

let refreshToken = null; // per VU: k6 gives every VU its own copy of module state

export default function () {
  if (!refreshToken) {
    const t = signIn(userFor(__VU), "openid profile email offline_access");
    refreshToken = t && t.refresh_token;
    if (!refreshToken) { sleep(1); return; }
  }
  const t = exchange({ grant_type: "refresh_token", client_id: FIXTURE.client_id, refresh_token: refreshToken });
  refreshToken = t ? t.refresh_token : null; // a failed rotation means starting over next iteration
  sleep(parseFloat(__ENV.THINK_SECONDS || "0.2"));
}

export function handleSummary(data) { return summary("refresh", data); }
