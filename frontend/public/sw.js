/* Push sign-in approval (IFORA-77). The push carries no data: it only wakes this worker, which shows a generic notification.
   The request itself (and the numbers to choose from) is fetched by /device/approve using this browser's own device secret. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  event.waitUntil(
    self.registration.showNotification("Approve this sign-in?", {
      body: "Open to see the request and pick the number shown on the sign-in screen.",
      tag: "ifora-signin",
      renotify: true,
      requireInteraction: true,
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      const open = wins.find((w) => new URL(w.url).pathname === "/device/approve");
      return open ? open.focus() : self.clients.openWindow("/device/approve");
    }),
  );
});
