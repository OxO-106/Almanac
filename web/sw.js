// Almanac's service worker: shows pushed notifications and opens the right screen.
self.addEventListener("push", event => {
  let n = { title: "Almanac", body: "", url: "#today" };
  try { n = { ...n, ...event.data.json() }; } catch { }
  event.waitUntil(self.registration.showNotification(n.title, {
    body: n.body, icon: "/static/icons/icon-192.png", badge: "/static/icons/icon-192.png", data: { url: n.url },
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const target = "/" + (event.notification.data?.url || "#today");
  event.waitUntil((async () => {
    const wins = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) { await w.navigate(target).catch(() => {}); return w.focus(); }
    return clients.openWindow(target);
  })());
});
