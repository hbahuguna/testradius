import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="harness", description="Vertical manual testing harness")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Run a test harness flow")
    sub.add_parser("context", help="Manage context bundles")
    sub.add_parser("eval", help="Run evaluations")
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    print(f"harness: {args.cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
