// /oauth/userinfo with a valid access token: the call every relying party makes most. IFORA-59.
import http from "k6/http";
import { check, sleep } from "k6";
import { BASE, p95, signIn, stages, steps, summary, thresholds, userFor } from "./lib.js";

export const options = {
  stages: stages(),
  thresholds: thresholds({ step_userinfo: [p95(200)] }),
};

let token = null; // per VU

export default function () {
  if (!token) {
    const t = signIn(userFor(__VU), "openid profile email");
    token = t && t.access_token;
    if (!token) { sleep(1); return; }
  }
  const r = http.get(`${BASE}/oauth/userinfo`, { headers: { Authorization: `Bearer ${token}` }, tags: { step: "userinfo" } });
  steps.userinfo.add(r.timings.duration);
  check(r, { "userinfo 200": (x) => x.status === 200 });
  if (r.status === 401) token = null; // expired: sign in again next iteration
  sleep(parseFloat(__ENV.THINK_SECONDS || "0.1"));
}

export function handleSummary(data) { return summary("userinfo", data); }
