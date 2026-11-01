/* Service worker: shows Web Push notifications; tapping opens the coin_url carried in the payload. No data cached. */
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("push", e => {
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch { d = { title: "Grok Bot", body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || "Grok Bot", {
    body: d.body || "", icon: d.icon || "/icons/icon-192.png", badge: "/icons/icon-192.png", tag: d.tag || undefined,
    data: { url: d.url || "https://pump.fun", mint: d.mint || null },
    actions: d.mint ? [{ action: "open", title: "Open on pump.fun" }, { action: "skip", title: "Skip" }] : [],
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const { url, mint } = e.notification.data || {};
  if (e.action === "skip" && mint) { e.waitUntil(self.clients.openWindow("/#/audit/" + mint)); return; }
  e.waitUntil(self.clients.openWindow(url || "https://pump.fun"));
});
