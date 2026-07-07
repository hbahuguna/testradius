import sys
from pathlib import Path


def _parse_flags(args: list[str]) -> tuple[list[str], str, str | None]:
    verbose = "INFO"
    log_file = None
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-v", "--verbose"):
            verbose = "DEBUG"
            i += 1
        elif a == "--log-file":
            i += 1
            if i < len(args):
                log_file = args[i]
                i += 1
            else:
                print("error: --log-file requires a path", file=sys.stderr)
                sys.exit(1)
        else:
            rest.append(a)
            i += 1
    return rest, verbose, log_file


def main():
    repo_path = Path.cwd()
    args = sys.argv[1:]

    if args and args[0] in ("-h", "--help"):
        print("Usage: testradius [OPTIONS] [COMMAND] [REPO_PATH]")
        print()
        print("Options:")
        print("  -v, --verbose       Enable DEBUG-level logging")
        print("  --log-file PATH     Write logs to file (default: stderr)")
        print()
        print("Commands:")
        print("  tui                 Start the Textual TUI (default)")
        print("  serve               Start headless HTTP server (port 9800)")
        print("  setup               Register plugin/skill in OpenCode config")
        print("  teardown            Remove testradius entries from OpenCode config")
        print()
        print("Arguments:")
        print("  REPO_PATH           Repository path (default: current directory)")
        print()
        print("Examples:")
        print("  testradius                         # TUI in current dir")
        print("  testradius serve                   # Headless API on :9800")
        print("  testradius setup                   # Configure OpenCode integration")
        print("  testradius serve -v                # API with debug logs")
        print("  testradius serve --log-file api.log # API logs to file")
        print("  testradius serve /path/to/repo     # API on :9800 for repo")
        print("  testradius tui   /path/to/repo     # TUI for repo")
        return

    args, verbose, log_file = _parse_flags(args)

    command = "tui"
    if args and args[0] in ("tui", "serve", "setup", "teardown"):
        command = args.pop(0)

    if args:
        repo_path = Path(args[0])
        if not repo_path.is_dir():
            print(f"error: {repo_path} is not a directory", file=sys.stderr)
            sys.exit(1)

    if command == "serve":
        _serve(str(repo_path.resolve()), verbose=verbose, log_file=log_file)
    elif command == "setup":
        _setup()
    elif command == "teardown":
        _teardown()
    else:
        _tui(str(repo_path.resolve()))


def _tui(repo_path: str):
    from .app import TestRadius
    app = TestRadius(repo_path=repo_path)
    app.run()


def _setup():
    import json

    config_path = Path.home() / ".config" / "opencode" / "opencode.json"
    if not config_path.exists():
        print(f"error: {config_path} not found. Is OpenCode installed?", file=sys.stderr)
        sys.exit(1)

    pkg_root = Path(__file__).resolve().parent
    plugin_path = pkg_root / "plugin" / "index.mjs"
    skill_path = pkg_root / "skill" / "SKILL.md"
    context_file = Path("/tmp/testradius-sdet-context.md")

    if not plugin_path.exists():
        print(f"error: plugin not found at {plugin_path}", file=sys.stderr)
        sys.exit(1)
    if not skill_path.exists():
        print(f"error: skill not found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    plugin_uri = f"file://{plugin_path}"
    skill_uri = f"file://{skill_path}"
    skill_name = "testradius-sdet"
    context_str = str(context_file)

    config.setdefault("plugin", [])
    if not isinstance(config.get("skills"), dict):
        config["skills"] = {}
    config.setdefault("instructions", [])

    added = []
    if plugin_uri not in config["plugin"]:
        config["plugin"].append(plugin_uri)
        added.append(f"  plugin: {plugin_uri}")
    if skill_uri not in config["skills"].values():
        key = skill_name
        if key in config["skills"]:
            i = 2
            while f"{skill_name}-{i}" in config["skills"]:
                i += 1
            key = f"{skill_name}-{i}"
        config["skills"][key] = skill_uri
        added.append(f"  skill ({key}): {skill_uri}")
    if context_str not in config["instructions"]:
        config["instructions"].append(context_str)
        added.append(f"  instructions: {context_str}")

    if not context_file.exists():
        content = (
            "## SDET Session Context (auto-injected)\n"
            "\n"
            "No active SDET session. "
            "Run `testradius serve` to start the server and enable auto-injection.\n"
        )
        context_file.write_text(content)
        added.append(f"  context file: {context_file}")

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    if added:
        print("testradius setup complete — added to OpenCode config:")
        for line in added:
            print(line)
    else:
        print("testradius is already configured in OpenCode (no changes needed).")


def _teardown():
    import json

    config_path = Path.home() / ".config" / "opencode" / "opencode.json"
    if not config_path.exists():
        print("OpenCode config not found; nothing to do.")
        return

    pkg_root = Path(__file__).resolve().parent
    plugin_uri = f"file://{pkg_root / 'plugin' / 'index.mjs'}"
    skill_uri = f"file://{pkg_root / 'skill' / 'SKILL.md'}"
    context_str = "/tmp/testradius-sdet-context.md"

    with open(config_path) as f:
        config = json.load(f)

    removed = []
    if plugin_uri in config.get("plugin", []):
        config["plugin"].remove(plugin_uri)
        removed.append(f"  plugin: {plugin_uri}")
    skills = config.get("skills", {})
    if isinstance(skills, dict):
        to_delete = [k for k, v in skills.items() if v == skill_uri]
        for k in to_delete:
            del skills[k]
            removed.append(f"  skills.{k}: {skill_uri}")
    if context_str in config.get("instructions", []):
        config["instructions"].remove(context_str)
        removed.append(f"  instructions: {context_str}")

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    if removed:
        print("testradius teardown — removed from OpenCode config:")
        for line in removed:
            print(line)
    else:
        print("No testradius entries found in OpenCode config.")


def _serve(
    repo_path: str | None = None,
    host: str = "127.0.0.1",
    port: int = 9800,
    verbose: str = "INFO",
    log_file: str | None = None,
):
    from .server.log_config import setup_logging
    from .server.http_server import LocalHTTPServer

    setup_logging(level=verbose, log_file=log_file)
    path = repo_path or str(Path.cwd().resolve())
    srv = LocalHTTPServer(repo_path=path, host=host, port=port)
    try:
        srv.start()
    except KeyboardInterrupt:
        srv.stop()
