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
        print()
        print("Arguments:")
        print("  REPO_PATH           Repository path (default: current directory)")
        print()
        print("Examples:")
        print("  testradius                         # TUI in current dir")
        print("  testradius serve                   # Headless API on :9800")
        print("  testradius serve -v                # API with debug logs")
        print("  testradius serve --log-file api.log # API logs to file")
        print("  testradius serve /path/to/repo     # API on :9800 for repo")
        print("  testradius tui   /path/to/repo     # TUI for repo")
        return

    args, verbose, log_file = _parse_flags(args)

    command = "tui"
    if args and args[0] in ("tui", "serve"):
        command = args.pop(0)

    if args:
        repo_path = Path(args[0])
        if not repo_path.is_dir():
            print(f"error: {repo_path} is not a directory", file=sys.stderr)
            sys.exit(1)

    if command == "serve":
        _serve(str(repo_path.resolve()), verbose=verbose, log_file=log_file)
    else:
        _tui(str(repo_path.resolve()))


def _tui(repo_path: str):
    from .app import TestRadius
    app = TestRadius(repo_path=repo_path)
    app.run()


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
