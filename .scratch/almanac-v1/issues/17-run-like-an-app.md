# 17: Run like an app

**What to build:** Almanac starts from the Start menu with a tray icon like Papercut, is reachable from the laptop at a private Tailscale HTTPS address, and backs up its database nightly keeping the last 14 copies.

**Blocked by:** 13 (Scheduler, notifications and Briefing)

**Status:** ready-for-agent

- [ ] Start-menu entry, tray icon, start/stop scripts
- [ ] Tailscale Serve on a separate HTTPS port
- [ ] Nightly backup job with retention
- [ ] README with run and setup steps
