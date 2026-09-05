# Hermes Telegram Miniapp

A small Telegram WebApp shell served by the Hermes API Server adapter.

Default routes:

- `/miniapp` — HTML shell
- `/miniapp/config.json` — browser-safe runtime config
- `/miniapp/api/report/latest` — latest sanitized visual report
- `/miniapp/assets/app.js` — frontend behavior
- `/miniapp/assets/styles.css` — visual style

This directory is intentionally plain HTML/CSS/JS so it can be deployed without a frontend build step.

## Current deployed URL

Smoke-tested public URL on Aidyn's Hetzner host:

```text
https://hetzner-tunnel.adntgv.com/miniapp
```

Deployment path:

- Cloudflare Tunnel public hostname: `hetzner-tunnel.adntgv.com`
- Cloudflare origin service: `http://localhost:8000`
- Local systemd forwarder: `hermes-api-cloudflare-tunnel.service`
- Forward target: Hermes API server at `127.0.0.1:8642`

Use this URL in BotFather or Telegram `web_app` buttons.

## Override without editing the repo

Set `platforms.api_server.extra.miniapp.static_dir` to a custom directory containing `index.html` and optional `assets/` files. Example:

```yaml
platforms:
  api_server:
    enabled: true
    extra:
      miniapp:
        static_dir: /root/.hermes/miniapp-lab
        app_name: Hermes Lab
        accent: "#0ea5e9"
```

Restart the gateway after config changes.
