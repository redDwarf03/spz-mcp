# spz-mcp

[![CI](https://github.com/redDwarf03/spz-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/redDwarf03/spz-mcp/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%E2%80%93%203.14-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

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
--agent-bridge-token=some-secret   # pins your own secret; normally unnecessary
```

The Unity console should log `[SPZ_Agent_Bridge] listening on 127.0.0.1:8765`.

**About the token.** The bridge requires one on every request. If you don't pin one,
the app generates a secret on first launch and writes it to
`%LOCALAPPDATA%/StableProjectorz/agent-bridge.token` (`~/.local/share/...` elsewhere).
This server reads that same file, so there is nothing to configure — and because it
re-reads until it finds one, starting this server before the app is fine.

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

For a non-default port, add `"env": {"SPZ_PORT": "8765"}`. The token is picked up
automatically.

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
| `--token` | `SPZ_TOKEN` | read from the token file |
| `--token-file` | `SPZ_TOKEN_FILE` | the app's well-known location |

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
without needing StableProjectorz running. Each test has a 30 s timeout: these all talk to a
local socket and finish in milliseconds, so a hang is a bug and should fail rather than
block the suite.

Linting and formatting use [ruff](https://docs.astral.sh/ruff/):

```bash
ruff check .
ruff format .
```

## CI/CD

`ci.yml` runs on every push to `main` and every pull request:

- **lint** — `ruff check` and `ruff format --check`
- **test** — Python 3.10 through 3.14 on Linux, plus one Windows leg (the app this server
  drives is Windows-first)
- **build** — builds the wheel and sdist and validates the metadata with `twine check`

`release.yml` runs on a `v*` tag. It refuses to proceed if the tag does not match the
version in `pyproject.toml`, then builds and attaches the distributions to a GitHub
release with generated notes.

Publishing to PyPI is **off by default**, since the server installs fine straight from git.
To enable it:

1. claim the `spz-mcp` name on PyPI
2. add a [trusted publisher](https://docs.pypi.org/trusted-publishers/) for this repo,
   workflow `release.yml`, environment `pypi`
3. set the repository variable `PUBLISH_TO_PYPI` to `true`

No token is stored anywhere — publishing authenticates over OIDC.

## License

MIT — see [LICENSE](LICENSE).

The StableProjectorz app itself is AGPL-3.0. This server is a separate program that
communicates with it over a socket, and is deliberately kept in its own repository so it
can be reused and relicensed independently.
