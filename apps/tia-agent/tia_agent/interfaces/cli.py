"""CLI entry point (`tia-agent`).

    tia-agent                      start the conversational REPL
    tia-agent analyze --repo OWNER/REPO --pr N [--commit SHA] [--json]
    tia-agent intake --repo OWNER/REPO --pr N [--path DIR] [--json]
    tia-agent activate --key TIA-XXXXXXXX-XXXXXXXX-XXXXXXXX
    tia-agent status
    tia-agent config show [--json]
    tia-agent llm show | set [--provider P --model M --key K] | test
    tia-agent backend up [--repo PATH] [--build SRC] | down | status
    tia-agent doctor
    tia-agent --version

Uses stdlib argparse so the artifact runs on clean machines with just Python.
Exits non-zero on failure so it composes in pipelines.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .. import __version__
from ..analyze import AnalyzeRunner, TiaResult
from ..config import TiaConfig
from ..errors import TiaError
from ..license_guard import LicenseGuard


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tia-agent", description="Standalone conversational TIA agent.")
    p.add_argument("--version", action="version", version=f"tia-agent {__version__}")
    p.add_argument("--config", default="", help="Path to config.json (default ~/.tia-agent/config.json)")

    sub = p.add_subparsers(dest="command")

    a = sub.add_parser("analyze", help="Run Test Impact Analysis on a PR")
    a.add_argument("--repo", required=True, help="GitHub repo, e.g. owner/repo")
    a.add_argument("--pr", required=True, type=int, help="PR number")
    a.add_argument("--commit", default="main", help="Commit SHA / branch (default: main)")
    a.add_argument("--file-paths", nargs="*", default=[], help="Override PR file paths (skips GitHub fetch)")
    a.add_argument("--repo-path", default="", help="Local checkout to validate/discover tests (default: TIA_REPO_PATH)")
    a.add_argument("--json", action="store_true", help="Emit machine-readable JSON result")

    intk = sub.add_parser("intake", help="Preview PR intake: changed source files + detected language")
    intk.add_argument("--repo", required=True, help="GitHub repo, e.g. owner/repo")
    intk.add_argument("--pr", required=True, type=int, help="PR number")
    intk.add_argument("--path", default="", help="Local repo path to detect the testbed language")
    intk.add_argument("--file-paths", nargs="*", default=[], help="Override PR file paths (skips GitHub fetch)")
    intk.add_argument("--no-prompt", action="store_true", help="Never prompt for a GitHub token")
    intk.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    act = sub.add_parser("activate", help="Activate this machine with a license key")
    act.add_argument("--key", required=True, help="TIA-XXXXXXXX-XXXXXXXX-XXXXXXXX")

    sub.add_parser("status", help="Show license status")

    cfg = sub.add_parser("config", help="Read/write agent configuration")
    cfg_sub = cfg.add_subparsers(dest="cfg_command")
    cfg_show = cfg_sub.add_parser("show", help="Show effective configuration")
    cfg_show.add_argument("--json", action="store_true")
    cfg_set = cfg_sub.add_parser("set", help="Set a config key, e.g. radius_url http://...")
    cfg_set.add_argument("key")
    cfg_set.add_argument("value")

    sub.add_parser("doctor", help="Check license + backend connectivity")

    be = sub.add_parser("backend", help="Start/stop the bundled local TestRadius backend")
    be_sub = be.add_subparsers(dest="be_command")
    be_up = be_sub.add_parser("up", help="Start core+db+neo4j and wait for health")
    be_up.add_argument("--repo", default="", help="Local repo path to mount at /workdir/<name>")
    be_up.add_argument("--build", default="", help="Build core from this source dir instead of pulling")
    be_up.add_argument("--port", type=int, default=0, help="Host port for the core API (default: from radius_url)")
    be_up.add_argument("--timeout", type=float, default=600.0, help="Health-wait timeout in seconds")
    be_up.add_argument("--json", action="store_true")
    be_down = be_sub.add_parser("down", help="Stop the bundled backend")
    be_down.add_argument("--json", action="store_true")
    be_status = be_sub.add_parser("status", help="Show bundled backend status")
    be_status.add_argument("--json", action="store_true")

    llm = sub.add_parser("llm", help="Configure your LLM provider (BYO key)")
    llm_sub = llm.add_subparsers(dest="llm_command")
    llm_show = llm_sub.add_parser("show", help="Show provider/model/key source (never the key)")
    llm_show.add_argument("--json", action="store_true")
    llm_set = llm_sub.add_parser("set", help="Set provider/model/key (prompts if flags omitted)")
    llm_set.add_argument("--provider", choices=("openai", "anthropic", "google", "ollama"))
    llm_set.add_argument("--model", default="", help="Model name (provider default if omitted)")
    llm_set.add_argument("--key", default="", help="API key (prompted hidden when omitted)")
    llm_test = llm_sub.add_parser("test", help="Send a tiny chat to verify the provider works")
    llm_test.add_argument("--prompt", default="Reply with exactly: OK")

    return p


def _load_config(args) -> TiaConfig:
    return TiaConfig.load(path=args.config) if args.config else TiaConfig.load()


def _print_result(result: TiaResult, as_json: bool) -> int:
    if as_json:
        from ..output import validate_output

        data = result.to_dict()
        errors = validate_output(data)
        if errors:
            print(json.dumps({"errors": errors}, indent=2), file=sys.stderr)
            return 1
        print(json.dumps(data, indent=2, default=str))
        return 0
    print(f"\nTIA result for {result.repo}#{result.pr_number}")
    print(f"  files analyzed : {result.files_analyzed}")
    print(f"  affected tests : {result.total_affected_tests}")
    print(f"  selected tests : {result.tests_selected}")
    if result.total_tests_in_repo:
        pct = f"{result.impacted_ratio:.0%}" if result.impacted_ratio is not None else "?"
        print(f"  suite size     : {result.total_tests_in_repo} tests ({pct} impacted)")
    print(f"  confidence     : {result.confidence}")
    if result.fallback_used:
        print(f"  [fallback]     : {result.fallback_reason}")
    if result.safety_flag:
        print("  [safety]       : >30% of the suite impacted — a full run is recommended")
    for t in result.tests:
        print(f"    - {t['name']:48s} {t['file']}")
    if result.run_commands:
        print("\n  run commands:")
        for c in result.run_commands:
            print(f"    $ {c}")
    print()
    return 0


def _cmd_analyze(args, config: TiaConfig) -> int:
    from ..creds import CredentialStore
    from ..errors import GitHubAuthError
    from .github_auth import ensure_github_token

    runner = AnalyzeRunner.build(config)
    files = args.file_paths or None
    if files is None:
        try:
            files = runner.fetch_files(args.repo, args.pr) or None
        except GitHubAuthError:
            token = ensure_github_token(config, CredentialStore())
            if token:
                runner.set_github_token(token)
                try:
                    files = runner.fetch_files(args.repo, args.pr) or None
                except TiaError:
                    files = None
        except TiaError:
            # Non-fatal: the backend can still fetch the PR with its own token.
            files = None
    result = runner.run(
        repo=args.repo,
        pr_number=args.pr,
        commit_sha=args.commit,
        file_paths=files,
        repo_path=args.repo_path or None,
    )
    return _print_result(result, args.json)


def _cmd_intake(args, config: TiaConfig) -> int:
    from ..creds import CredentialStore
    from ..tools.github import GitHubClient, filter_source_files
    from ..tools.language import detect_language_from_files, detect_language_from_repo
    from .github_auth import ensure_github_token, token_source

    store = CredentialStore()
    files = list(args.file_paths)
    if not files:
        token = ensure_github_token(config, store, allow_prompt=not args.no_prompt)
        with GitHubClient(token or config.github_token) as gh:
            files = filter_source_files(gh.get_pr_files(args.repo, args.pr))

    language = (
        detect_language_from_repo(args.path) if args.path
        else detect_language_from_files(files)
    )
    payload = {
        "repo": args.repo,
        "pr_number": args.pr,
        "file_count": len(files),
        "files": files,
        "language": language.language,
        "confidence": language.confidence,
        "instrumentation_language": language.instrumentation_language,
        "evidence": language.evidence,
        "github_token_source": token_source(config, store),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"repo          : {args.repo}#{args.pr}")
    print(f"github token  : {payload['github_token_source']}")
    print(f"language      : {language.language} ({language.confidence}) -> "
          f"{language.instrumentation_language}")
    print(f"source files  : {len(files)}")
    for f in files:
        print(f"  - {f}")
    return 0


def _cmd_activate(args, config: TiaConfig) -> int:
    guard = LicenseGuard(config)
    info = guard.activate(args.key)
    print(f"Activated. subscription={info['subscription_status']} quota_remaining={info['quota_remaining']}")
    return 0


def _cmd_status(config: TiaConfig) -> int:
    guard = LicenseGuard(config)
    info = guard.status()
    print(json.dumps(info, indent=2, default=str))
    return 0 if info.get("status") in ("valid",) else 1


def _cmd_config(args, config: TiaConfig) -> int:
    if args.cfg_command == "show":
        if args.json:
            print(json.dumps(config.__dict__, indent=2, default=str))
        else:
            import dataclasses

            for f in dataclasses.fields(config):
                print(f"{f.name:16s} = {getattr(config, f.name)}")
        return 0
    if args.cfg_command == "set":
        setattr(config, args.key, args.value)
        config.save()
        print(f"set {args.key} = {args.value}")
        return 0
    print("config: unknown subcommand. Use: show | set")
    return 2


def _cmd_doctor(config: TiaConfig) -> int:
    from ..radius_client import RadiusClient
    from ..backend import docker_available

    ok = True
    print(f"docker: {'OK' if docker_available() else 'NOT AVAILABLE'}")
    guard = LicenseGuard(config)
    info = guard.status()
    print(f"license: {info}")
    if info.get("status") != "valid":
        ok = False
    with RadiusClient(config.radius_url, config.radius_token) as radius:
        healthy = radius.health()
        print(f"backend: {'OK' if healthy else 'UNREACHABLE'} at {config.radius_url}")
        if not healthy:
            ok = False
        print(f"projects: {len(radius.list_projects())} registered")
    print("done.")
    return 0 if ok else 1


def _cmd_llm(args, config: TiaConfig) -> int:
    from ..creds import CredentialStore
    from ..llm import DEFAULT_MODELS, ENV_KEYS, llm_status, resolve_api_key, chat

    store = CredentialStore()

    if args.llm_command == "show" or args.llm_command is None:
        info = llm_status(config, store)
        if getattr(args, "json", False):
            print(json.dumps(info, indent=2))
        else:
            for k, v in info.items():
                print(f"{k:18s} {v}")
            if info["key_source"] == "MISSING":
                print(f"  -> set ${ENV_KEYS.get(config.llm_provider, '')} or run `tia-agent llm set`")
        return 0

    if args.llm_command == "set":
        if not args.provider:
            from .onboarding import run_onboarding

            return 0 if run_onboarding(config, store) else 2
        config.llm_provider = args.provider
        config.llm_model = args.model or DEFAULT_MODELS[args.provider]
        if args.provider != "ollama":
            key = args.key
            if not key and sys.stdin.isatty():
                import getpass

                key = getpass.getpass(f"{args.provider} API key (hidden): ").strip()
            if key:
                store.set(args.provider, key)
                print(f"Key stored in {store.backend_name}.")
            elif not resolve_api_key(args.provider, store):
                print(f"warning: no key provided — {args.provider} calls will fail until you set one.",
                      file=sys.stderr)
        config.save()
        print(f"provider = {config.llm_provider}  model = {config.llm_model}")
        return 0

    if args.llm_command == "test":
        resp = chat(config, [{"role": "user", "content": args.prompt}], store)
        text = resp.text.strip()
        print(f"{resp.provider}/{resp.model}: {text[:500]}")
        return 0 if text else 1

    print("llm: unknown subcommand. Use: show | set | test", file=sys.stderr)
    return 2


def _cmd_backend(args, config: TiaConfig) -> int:
    from ..backend import BackendManager, docker_available, port_from_url

    command = getattr(args, "be_command", None)
    if command is None:
        print("backend: choose a subcommand. Use: up | down | status", file=sys.stderr)
        return 2

    port = getattr(args, "port", 0) or port_from_url(config.radius_url)
    manager = BackendManager(
        core_port=port,
        build_source=(getattr(args, "build", "") or None),
    )

    if command == "up":
        if not docker_available():
            print("error: Docker is not available (install/start Docker Desktop).", file=sys.stderr)
            return 8
        status = manager.up(
            repo_path=(getattr(args, "repo", "") or None),
            timeout=getattr(args, "timeout", 600.0),
            pull=not getattr(args, "build", ""),
        )
    elif command == "down":
        manager.down()
        status = manager.status()
    else:  # status
        status = manager.status()

    if getattr(args, "json", False):
        print(json.dumps(status.to_dict(), indent=2))
    else:
        print(f"backend: running={status.running} healthy={status.healthy} ({status.detail})")
    if command == "up":
        print(f"API: http://localhost:{port}")
    return 0 if (command == "down" or status.healthy) else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        from .repl import Repl

        return Repl(_load_config(args)).run()

    try:
        config = _load_config(args)
        if args.command == "analyze":
            return _cmd_analyze(args, config)
        if args.command == "intake":
            return _cmd_intake(args, config)
        if args.command == "activate":
            return _cmd_activate(args, config)
        if args.command == "status":
            return _cmd_status(config)
        if args.command == "config":
            return _cmd_config(args, config)
        if args.command == "doctor":
            return _cmd_doctor(config)
        if args.command == "llm":
            return _cmd_llm(args, config)
        if args.command == "backend":
            return _cmd_backend(args, config)
    except TiaError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.exit_code
    except Exception as e:  # noqa: BLE001 - surface everything to the CLI
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("error: unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())