import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="harness", description="Vertical manual testing harness")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Run a test harness flow")
    ctx = sub.add_parser("context", help="Manage context bundles")
    ctx_sub = ctx.add_subparsers(dest="ctx_cmd")
    ctx_validate = ctx_sub.add_parser("validate")
    ctx_validate.add_argument("file")
    sub.add_parser("eval", help="Run evaluations")
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    if args.cmd == "context":
        if args.ctx_cmd == "validate":
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
    print(f"harness: {args.cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
