---
name: connect-chatgpt
description: Runbook for connecting ChatGPT to this project's MCP server through the OpenAI Secure MCP Tunnel, plus the known gotchas. Use when setting up, starting, or debugging the ChatGPT tunnel or the "Computer History" ChatGPT plugin.
---

```
ChatGPT → OpenAI Secure MCP Tunnel → tunnel-client on the Mac → http://127.0.0.1:8765/mcp
```

1. Start ActivityWatch and the backend: `.venv/bin/python history.py serve`
   (no `--reload` while the tunnel is connected).
2. In a **second** terminal, set the runtime API key (it lasts only for that
   terminal session):
   ```bash
   read -s "CONTROL_PLANE_API_KEY?Paste runtime API key: "
   echo
   export CONTROL_PLANE_API_KEY
   ```
3. Start the tunnel client in that same terminal:
   ```bash
   cd ~/Downloads/tunnel-client-v0.0.20-darwin-arm64
   ./tunnel-client run \
     --profile computer-history \
     --control-plane.organization-id YOUR_ORG_ID
   ```
4. Keep the backend and the tunnel running.
5. In the **matching** ChatGPT workspace, install/select the custom
   "Computer History" plugin, start a **new** chat, and explicitly ask it to
   use that plugin.

## Gotchas already hit (check these first)

- One account/organization everywhere: the ChatGPT account/workspace, the
  OpenAI Platform organization, the tunnel's organization and workspace
  associations, the runtime API key's organization, and the tunnel ID in the
  local profile and the plugin setup. Sign Platform and ChatGPT in to the
  same account.
- Pass the organization ID explicitly (`--control-plane.organization-id`).
- macOS blocks the unsigned `tunnel-client` until approved in System Settings
  → Privacy & Security.
- `CONTROL_PLANE_API_KEY` vanishes when you switch Terminal windows; set it in
  the terminal that runs the tunnel.
- ChatGPT rate-limits plugin creation after repeated failures; wait before
  retrying.
- Plugin tools missing from a chat means the conversation or plugin install,
  not the backend: start a new chat.

Never commit the API key or org ID to this repo.
