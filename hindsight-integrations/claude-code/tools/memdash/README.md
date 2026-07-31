# memdash — Memory System Dashboard

Personal tooling (fork-only, not intended for upstream): monitors the
three-store memory setup used with the Claude Code plugin — Hindsight
(auto capture/recall), agentmemory (read-only archive), and Claude Code's
native MEMORY.md files.

## Terminal snapshot

```bash
python3 memdash.py             # full (live recall p50/p95 bench, ~1s)
python3 memdash.py --no-bench  # instant
```

Sections: system health (daemons + hook wiring), storage (per-bank
nodes/docs/links, archive count, native files), pipeline activity
(last recall, per-session turn counters, retention progress, failed ops),
performance (live recall p50/p95 + A/B log), trend (snapshots accumulate
in `~/.claude/memdash_history.jsonl`).

## Web dashboard

```bash
python3 memdash_web.py --port 9090   # → http://localhost:9090
```

Zero-dependency (stdlib http.server) page with an overall
HEALTHY / DEGRADED / UNHEALTHY indicator (with reasons), card grid for
all metrics, 10s auto-refresh (live bench once per minute).

### Run as a systemd user service

```ini
# ~/.config/systemd/user/memdash-web.service
[Unit]
Description=Memory System Dashboard (memdash web, :9090)
After=network-online.target

[Service]
WorkingDirectory=%h/z_Setup/Claude_MemorySystem
ExecStart=/usr/bin/python3 %h/z_Setup/Claude_MemorySystem/memdash_web.py --port 9090
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now memdash-web
```

### GNOME dock launcher

`~/.local/share/applications/memdash.desktop` with
`Exec=xdg-open http://localhost:9090`, then add `memdash.desktop` to
`org.gnome.shell favorite-apps`.

Note: the live deployment runs from `~/z_Setup/Claude_MemorySystem`;
this directory is the version-controlled copy. Paths for state/history
(`~/.claude/...`) and service endpoints (:9077/:3111/:11434) are
machine-specific.
