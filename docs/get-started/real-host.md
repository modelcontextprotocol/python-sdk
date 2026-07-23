# Connect to a real host

A **host** is the application your server ends up inside: Claude Desktop, Claude Code, an IDE. The host is what the user talks to. Inside it, an MCP **client** launches your server as a child process and speaks to it over that process's stdin and stdout.

Which means connecting to a host is one act: you tell it **the command that starts your server**. Everything on this page (two CLI commands, three JSON files) is a different place to put that same command.

## One server, every host

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

Two tools and a resource, one file. Three things about that file matter to every host below:

* `mcp.run()` with no arguments starts a **stdio** server: it blocks, reads protocol messages on stdin, and writes them on stdout. That is the transport every host on this page speaks. The host starts your file as a child process and owns those two pipes, which is why connecting is only ever "here is the command". You never pick a port, and nothing listens on one.
* `run()` is under `if __name__ == "__main__":`. Everything below **imports** this file rather than executing it, so an unguarded `run()` would start a server the moment anything loaded the module.
* The server object is a module-level global named `mcp`. That's the name `mcp run` looks for (`server` and `app` also work). Call it something else and you name it explicitly: `mcp run server.py:bookshop`.

That is the last line of Python on this page. From here down it is all host configuration.

## The launch command

Every host below gets the same command:

```bash
uv run --with "mcp[cli]==2.0.0b1" mcp run /absolute/path/to/server.py
```

One command for all of them because `uv run --with` resolves the pinned SDK into a fresh environment on the spot: it works from any directory, needs no project and no virtual environment to activate, and always gets the exact `mcp` version these docs describe. That matters here more than anywhere else, because a host launches your server from *its* working directory with a near-empty environment, not from your shell.

It is also the command `mcp install` writes into Claude Desktop's config for you (below), so what you type by hand and what the tool generates agree.

!!! warning "The version pin is not optional"
    v2 of this SDK is in beta, and installers never select a pre-release unless you name one. An
    unpinned `--with "mcp[cli]"` gives you the latest **v1.x**, which these docs do not describe.
    Use the exact pin from **[Installation](installation.md)**.

!!! tip "If a host can't find `uv`"
    A host spawns your server with a minimal `PATH`, and `uv` may not be on it. Replace the bare
    `uv` with the absolute path from `which uv` (macOS/Linux) or `where uv` (Windows). That is
    exactly what `mcp install` writes.

!!! note "This page is the local story"
    Everything here runs your server on the machine the host is on: the host launches your
    file, over stdio. That is exactly right for a personal or single-machine tool. To give a
    server to people who do *not* have your file, you hand out a **URL**, not a command: the
    same `mcp` object served over Streamable HTTP. **[Running your server](../run/index.md)**
    is that decision in one table, and **[Deploy & scale](../run/deploy.md)** is the road from
    there to a real hostname.

    And a host is nothing more than an application with an MCP client inside it, so your own
    Python can play the host's part: **[Client transports](../client/transports.md)** launches
    this same file as a subprocess with `stdio_client(...)`, and **[Testing](testing.md)**
    connects to it in memory with no process at all.

## Claude Desktop

The one host the SDK can configure for you:

```bash
uv run mcp install server.py
```

That's it. `mcp install` imports the file to read the server's name, finds Claude Desktop's config file, and writes the launch command into it. Along the way it converts your path to an absolute one, so you don't have to.

There is nothing to be mystified by. This is the entry it writes:

```json
{
  "mcpServers": {
    "Bookshop": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--frozen",
        "--with",
        "mcp[cli]==2.0.0b1",
        "mcp",
        "run",
        "/absolute/path/to/server.py"
      ]
    }
  }
}
```

That's the launch command from the section above with two additions: the absolute path to `uv`, and `--frozen` so `uv` never rewrites a lockfile it happens to be near. It lands in `claude_desktop_config.json`, which lives at:

* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

You can write that file by hand. `mcp install` exists so you don't make the two classic mistakes (a relative path, a missing version pin) while doing it.

Fully quit Claude Desktop (not just its window) and reopen it.

!!! warning
    `mcp install` fails with `Claude app not found` if Claude Desktop's config *directory* doesn't
    exist yet. Install Claude Desktop and run it once: that's what creates the directory.

!!! tip
    Claude Desktop starts your server in its own process, so your shell's environment variables are
    not there. `uv run mcp install server.py -v API_KEY=abc123` (or `-f .env`) records them in the
    entry's `env` field. `--name` overrides the entry name; it defaults to the server's `name`.

## Claude Code

There is no file to edit. Register the server with the `claude` CLI; everything after `--` is the launch command.

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]==2.0.0b1" mcp run /absolute/path/to/server.py
```

Run `/mcp` inside a Claude Code session to confirm `bookshop` is connected and its tools are listed.

## Cursor

Create `.cursor/mcp.json` in your project root.

```json
{
  "mcpServers": {
    "bookshop": {
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]==2.0.0b1", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

The same `command` plus `args`, under the same `mcpServers` key Claude Desktop uses. The server appears in Cursor's MCP settings with both tools listed.

## VS Code

Create `.vscode/mcp.json` in your project root.

```json
{
  "servers": {
    "bookshop": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]==2.0.0b1", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

Two differences from Cursor's file, and they are the only two: the wrapper key is `servers`, not `mcpServers`, and each entry declares its `type`. Confirm the trust prompt, then **MCP: List Servers** in the Command Palette shows `bookshop` running.

!!! note
    You need VS Code 1.99 or later with the **GitHub Copilot** extension signed in (Copilot Free is
    enough), and Copilot Chat must be in **Agent** mode, because no other mode calls tools.

## It doesn't show up

Before you touch any host config, run the launch command yourself:

```bash
uv run --with "mcp[cli]==2.0.0b1" mcp run /absolute/path/to/server.py
```

Nothing prints, and it doesn't return. That silence is correct: a stdio server is waiting for a host to speak first on stdin (`Ctrl-C` to stop it). A traceback or an immediate exit is the real bug, and now you can read it instead of guessing at it through a host.

Once that command sits and waits, what's left is almost always one of three things:

* **A relative path.** The host launches your server from *its* working directory, not the one you registered from. `server.py` where `/absolute/path/to/server.py` is needed is the single most common failure. If the host can't find `uv` either, that path has to be absolute too.
* **The host is still running its old config.** Hosts read their config at launch. Claude Desktop in particular has to be *fully quit* (not just its window closed) and reopened before an edit to `claude_desktop_config.json` takes effect.
* **Something reached stdout outside the diverted window.** On stdio, stdout *is* the protocol. The SDK diverts flushed stray output to stderr while serving, but output flushed to stdout before then (a wrapper script echoing, an import-time `print()` in an unbuffered process), or a buffered `print()` drained at interpreter exit, hands the host a corrupt message and it drops the connection. Log with the `logging` module, which flushes each record to stderr. **[Logging](../handlers/logging.md)** has the whole story.

Claude Desktop keeps a log per server: `mcp-server-<NAME>.log` is your server's stderr, next to `mcp.log` for connections, under `~/Library/Logs/Claude` on macOS and `%APPDATA%\Claude\logs` on Windows.

For anything past those three, **[Troubleshooting](../troubleshooting.md)** is the page.

## Recap

* A **host** (Claude Desktop, an IDE) runs an MCP client that launches your server as a child process over stdio. Connecting means giving it one launch command.
* That command is `uv run --with "mcp[cli]==2.0.0b1" mcp run /absolute/path/to/server.py`: version-pinned, no venv to activate, works from any directory. The pin is mandatory while v2 is in beta.
* **Claude Desktop** is the one host `mcp install` configures for you. It writes that same command (plus the absolute path to `uv`) into `claude_desktop_config.json`, so you never have to.
* **Claude Code** is `claude mcp add bookshop -- <launch command>`. **Cursor** is `.cursor/mcp.json` under `mcpServers`. **VS Code** is `.vscode/mcp.json` under `servers`, each entry with a `type`.
* Absolute paths everywhere, restart the host after editing its config, and never let anything but the SDK write to stdout.

Every host on this page connected to the same file, with the same command. What that file can *expose* is the rest of these docs: **[Tools](../servers/tools.md)**, **[Resources](../servers/resources.md)**, and every transport besides stdio in **[Running your server](../run/index.md)**.
