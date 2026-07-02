import sys
from pathlib import Path


def main():
    repo_path = Path.cwd()
    args = sys.argv[1:]

    if args and args[0] in ("-h", "--help"):
        print("Usage: testradius [COMMAND] [REPO_PATH]")
        print()
        print("Commands:")
        print("  tui             Start the Textual TUI (default)")
        print("  serve           Start headless HTTP server (port 9800)")
        print()
        print("Arguments:")
        print("  REPO_PATH       Repository path (default: current directory)")
        print()
        print("Examples:")
        print("  testradius                     # TUI in current dir")
        print("  testradius serve               # Headless API on :9800")
        print("  testradius serve /path/to/repo # API on :9800 for repo")
        print("  testradius tui   /path/to/repo # TUI for repo")
        return

    command = "tui"
    if args and args[0] in ("tui", "serve"):
        command = args.pop(0)

    if args:
        repo_path = Path(args[0])
        if not repo_path.is_dir():
            print(f"error: {repo_path} is not a directory", file=sys.stderr)
            sys.exit(1)

    if command == "serve":
        _serve(str(repo_path.resolve()))
    else:
        _tui(str(repo_path.resolve()))


def _tui(repo_path: str):
    from .app import TestRadius
    app = TestRadius(repo_path=repo_path)
    app.run()


def _serve(repo_path: str | None = None, host: str = "127.0.0.1", port: int = 9800):
    from .server.http_server import LocalHTTPServer
    path = repo_path or str(Path.cwd().resolve())
    print(f"[testradius] serving tools from {path}")
    srv = LocalHTTPServer(repo_path=path, host=host, port=port)
    try:
        srv.start()
    except KeyboardInterrupt:
        srv.stop()
        print("[testradius] stopped")
