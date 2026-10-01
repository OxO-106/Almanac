# 21: iPhone Home Screen app and push

**What to build:** Almanac works well at phone width and can be added to the iPhone Home Screen over Tailscale. There, the student can turn on push notifications: the briefing, check-ins, timer and overviews arrive as iOS notifications (Web Push via Apple, end-to-end encrypted, VAPID keys kept locally).

**Blocked by:** 13 (Scheduler, notifications), 17 (Run like an app)

**Status:** done

- [x] Service worker at the site root
- [x] VAPID keys generated once and stored locally
- [x] Subscribe from a device; every notification is pushed to subscribed devices; dead subscriptions removed
- [x] Phone layout checked at 375px
- [x] API tests with a fake push sender
