# Using aoe2coach from Claude (MCP) — no API key

Besides the primary API path (`aoe2coach analyze`), aoe2coach ships an **MCP server**, so
you can use it *inside* Claude Code or Claude Desktop and coach with your assistant's own
model — no `ANTHROPIC_API_KEY`, no per-call cost beyond your Claude plan.

> Status: this path works, but it is still a work in progress. The next polish pass is
> packaged config snippets, clearer install steps, and better replay-selection UX.

## API path vs MCP path — same brain, different shape

Both run the **identical** parse→metrics pipeline and the same coaching instructions; they
differ only in how the model is used:

| | **API path** (`aoe2coach analyze`) | **MCP path** (Claude Code / Desktop) |
|---|---|---|
| Model | Your API key (Anthropic / OpenAI-compatible) | Your Claude subscription |
| Shape | One-shot **workflow** — computes stats, one model call, saves a report | **Agent** — Claude calls the tools and you **converse** |
| System prompt | aoe2coach's `system.md` *is* the system prompt | The app's own; aoe2coach's framing rides in via the `coach` prompt |
| Cost | Pay the provider per run | None beyond your plan |

> Note: in **free-chat** ("analyze my latest replay") the app uses its own coaching; to get
> aoe2coach's exact framing, invoke the **`coach`** prompt.

## What the server exposes

- **Tools:** `list_replays`, `replay_metrics` (metrics + civ context), `replay_trends`
- **Prompts:** `coach`, `coach_trends` — inject the full system prompt + benchmarks so the
  client coaches the way the API path does.

## Set it up

Install with the `mcp` extra (plus a parser backend):

```bash
pip install -e ".[full,mcp]"     # or ".[fast,mcp]" for current-patch games
```

### Claude Code (terminal)

```bash
claude mcp add aoe2coach -- /ABSOLUTE/PATH/.venv/bin/python -m aoe2coach.mcp_server
```
Start a new `claude` session, then ask *"analyze my latest replay"* or invoke `/aoe2coach:coach`.

### Claude Desktop (GUI)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "aoe2coach": {
      "command": "/ABSOLUTE/PATH/.venv/bin/python",
      "args": ["-m", "aoe2coach.mcp_server"]
    }
  }
}
```
Quit and reopen Claude Desktop; the `coach` prompt appears in the `+` menu.
