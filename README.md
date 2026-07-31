# spz-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an LLM agent drive
[StableProjectorz](https://stableprojectorz.com) — inspect the loaded 3D model, read the
app's state, look at the viewport, and trigger UI actions.

It talks to the **agent bridge** built into the app: a loopback-only JSON socket.

```
Claude Code / Claude Desktop  ──MCP(stdio)──►  spz-mcp  ──TCP 127.0.0.1:8765──►  StableProjectorz
```

## The server knows nothing about StableProjectorz

On every `tools/list`, it asks the running app for its catalogue via the bridge's
`describe` command and republishes it as MCP tools, building each JSON Schema from the
parameter descriptions the app supplies.

Nothing is hard-coded here. **Adding a tool to the app does not require a new release of
this server** — which is exactly what allows the app and this server to live in separate
repositories without drifting apart.

## Setup

### 1. Enable the bridge in StableProjectorz

Add this to `spz.config`, next to the executable (or at the project root when running
from the Unity Editor), then restart the app:

```
--agent-bridge
```

Optional:

```
--agent-bridge-port=8765
--agent-bridge-token=some-secret
```

The Unity console should log `[SPZ_Agent_Bridge] listening on 127.0.0.1:8765`.

### 2. Register the server

Claude Code:

```bash
claude mcp add spz -- uvx --from git+https://github.com/redDwarf03/spz-mcp spz-mcp
```

Claude Desktop — in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "spz": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/redDwarf03/spz-mcp", "spz-mcp"]
    }
  }
}
```

With a token or a non-default port, add `"env": {"SPZ_TOKEN": "some-secret", "SPZ_PORT": "8765"}`.

### From a local checkout

```bash
pip install -e ".[dev]"
spz-mcp --port 8765
```

## Tools

The list comes from the app at runtime. With the current bridge you get:

| Tool | What it does |
|---|---|
| `describe` | Protocol version and tool catalogue |
| `get_app_state` | Version, WebUI connections, loaded model, UDIM tiles, selection, generation status |
| `get_viewport_screenshot` | Viewport capture, returned as a real MCP image the agent can see |
| `list_generations` | Stored generation counts per kind, and the latest GUID |
| `list_events` | Every registered `StaticEvents` id and its parameter types |
| `invoke_event` | Fire a `StaticEvents` id, as the matching UI control would |

Plus one tool this server adds itself:

| Tool | What it does |
|---|---|
| `spz_bridge_status` | Whether the app is reachable, and how to enable the bridge if not |

`spz_bridge_status` is also the only tool published while the app is down, so an agent can
diagnose the situation instead of finding an unexplained empty toolbox.

## Options

| Flag | Env | Default |
|---|---|---|
| `--host` | `SPZ_HOST` | `127.0.0.1` |
| `--port` | `SPZ_PORT` | `8765` |
| `--token` | `SPZ_TOKEN` | none |

## Protocol

One JSON object per line over TCP:

```
->  {"id":"1","tool":"get_app_state","params":{}}
<-  {"id":"1","ok":true,"result":{"app_version":"2.4.5","sd_connected":true, ...}}
<-  {"id":"1","ok":false,"error":"unknown tool 'foo'. Call 'describe' for the catalogue."}
```

The app serves one request at a time per connection, so this client serialises calls
behind a lock rather than multiplexing on `id`.

## Notes and limits

- The bridge is **opt-in and loopback-only**, but it is an unauthenticated local control
  channel unless you set a token. Any process on the machine can connect. Enable it only
  while you are using it.
- Screenshots wait on an async GPU readback, so they can take a moment; overlapping
  captures are rejected rather than left hanging.
- Managers in the app live in additively-loaded scenes, so calls made during startup may
  report that a subsystem is not ready yet.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The suite runs a fake bridge over a real TCP socket, so the client is exercised end to end
without needing StableProjectorz running.

## License

MIT — see [LICENSE](LICENSE).

The StableProjectorz app itself is AGPL-3.0. This server is a separate program that
communicates with it over a socket, and is deliberately kept in its own repository so it
can be reused and relicensed independently.
