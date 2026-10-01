# 21: iPhone Home Screen app and push

**What to build:** Almanac works well at phone width and can be added to the iPhone Home Screen over Tailscale. There, the student can turn on push notifications: the briefing, check-ins, timer and overviews arrive as iOS notifications (Web Push via Apple, end-to-end encrypted, VAPID keys kept locally).

**Blocked by:** 13 (Scheduler, notifications), 17 (Run like an app)

**Status:** ready-for-agent

- [ ] Service worker at the site root
- [ ] VAPID keys generated once and stored locally
- [ ] Subscribe from a device; every notification is pushed to subscribed devices; dead subscriptions removed
- [ ] Phone layout checked at 375px
- [ ] API tests with a fake push sender
