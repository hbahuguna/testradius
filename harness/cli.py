import argparse
import sys


def _cmd_context(args):
    if len(args) >= 2 and args[0] == "validate":
        try:
            from .context.loader import validate_context
            c = validate_context(args[1])
            print(f"valid: {c.ticket_id} - {c.title}")
            return 0
        except Exception as e:
            print(f"invalid: {e}")
            return 1
    if len(args) == 2:
        try:
            from .context.loader import validate_context
            c = validate_context(args[1])
            print(f"valid: {c.ticket_id} - {c.title}")
            return 0
        except Exception as e:
            print(f"invalid: {e}")
            return 1
    print("usage: harness context validate <file>")
    return 1


def _cmd_run(args):
    if not args or args[0] != "smoke":
        print("usage: harness run smoke")
        return 1
    try:
        from .run.smoke import run_smoke
        r, rp = run_smoke()
        print(f"PASS - report: {rp}")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 1


def _cmd_testradius(args):
    if args and args[0] == "execute":
        try:
            from .runner import execute_testradius_plan
            r, rp = execute_testradius_plan()
            print(f"COMPLETED - report: {rp}")
            return 0
        except Exception as e:
            print(f"FAIL: {e}")
            return 1
    if args and args[0] == "run":
        try:
            from .runner.execute_testradius_real import execute_testradius_real
            r, rp = execute_testradius_real(headless=True)
            print(f"COMPLETED - report: {rp}")
            return 0
        except Exception as e:
            print(f"FAIL: {e}")
            return 1
    try:
        from .runner import run_testradius_e2e
        r, rp = run_testradius_e2e()
        print(f"PASS - report: {rp}")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="harness", description="Vertical manual testing harness")
    sub = parser.add_subparsers(dest="cmd")
    ctx = sub.add_parser("context", help="Manage context bundles")
    ctx_sub = ctx.add_subparsers(dest="ctx_cmd")
    v = ctx_sub.add_parser("validate")
    v.add_argument("file")
    runp = sub.add_parser("run", help="Run a test harness flow")
    run_sub = runp.add_subparsers(dest="run_cmd")
    run_sub.add_parser("smoke")
    sub.add_parser("eval", help="Run evaluations")
    tr = sub.add_parser("testradius", help="Run E2E against testradius.dev")
    tr_sub = tr.add_subparsers(dest="tr_cmd")
    tr_sub.add_parser("execute")
    tr_sub.add_parser("run")
    args, rest = parser.parse_known_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    if args.cmd == "context":
        if getattr(args, "ctx_cmd", None) == "validate":
            try:
                from .context.loader import validate_context
                c = validate_context(args.file)
                print(f"valid: {c.ticket_id} - {c.title}")
                return 0
            except Exception as e:
                print(f"invalid: {e}")
                return 1
        ctx.print_help()
        return 1
    if args.cmd == "run":
        if getattr(args, "run_cmd", None) == "smoke":
            try:
                from .run.smoke import run_smoke
                r, rp = run_smoke()
                print(f"PASS - report: {rp}")
                return 0
            except Exception as e:
                print(f"FAIL: {e}")
                return 1
        runp.print_help()
        return 1
    if args.cmd == "testradius":
        if rest and rest[0] == "execute":
            try:
                from .runner import execute_testradius_plan
                r, rp = execute_testradius_plan()
                print(f"COMPLETED - report: {rp}")
                return 0
            except Exception as e:
                print(f"FAIL: {e}")
                return 1
        if rest and rest[0] == "run":
            try:
                from .runner.execute_testradius_real import execute_testradius_real
                r, rp = execute_testradius_real(headless=True)
                print(f"COMPLETED - report: {rp}")
                return 0
            except Exception as e:
                print(f"FAIL: {e}")
                return 1
        if getattr(args, "tr_cmd", None) == "execute":
            try:
                from .runner import execute_testradius_plan
                r, rp = execute_testradius_plan()
                print(f"COMPLETED - report: {rp}")
                return 0
            except Exception as e:
                print(f"FAIL: {e}")
                return 1
        if getattr(args, "tr_cmd", None) == "run":
            try:
                from .runner.execute_testradius_real import execute_testradius_real
                r, rp = execute_testradius_real(headless=True)
                print(f"COMPLETED - report: {rp}")
                return 0
            except Exception as e:
                print(f"FAIL: {e}")
                return 1
        return _cmd_testradius(rest)
    print(f"harness: {args.cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
