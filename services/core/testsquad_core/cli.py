import asyncio
import argparse
import sys
from uuid import UUID
from testsquad_core.clients.executor import ExecutorClient
from testsquad_shared.api import ExecutionRequest

async def main():
    parser = argparse.ArgumentParser(description="TestSquad Core CLI")
    subparsers = parser.add_subparsers(dest="command")

    exec_parser = subparsers.add_parser("execute", help="Trigger a test run")
    exec_parser.add_argument("--repo", default="test-repo", help="Repository URL")
    exec_parser.add_argument("--cmd", default="echo 'Hello from Sandbox'", help="Command to run")

    stream_parser = subparsers.add_parser("stream", help="Stream logs for a run")
    stream_parser.add_argument("run_id", type=str, help="Run ID to stream")

    args = parser.parse_args()
    client = ExecutorClient() # Defaults to http://executor:8001

    if args.command == "execute":
        request = ExecutionRequest(
            repo_url=args.repo,
            command=args.cmd
        )
        try:
            response = await client.execute_task(request)
            print(f"Run triggered successfully!")
            print(f"Run ID: {response.run_id}")
            print(f"Status: {response.status}")
        except Exception as e:
            print(f"Error triggering run: {e}")

    elif args.command == "stream":
        try:
            run_id = UUID(args.run_id)
            print(f"Streaming logs for {run_id}...")
            async for log in client.stream_logs(run_id):
                print(log, end="", flush=True)
        except Exception as e:
            print(f"Error streaming logs: {e}")

    else:
        parser.print_help()

if __name__ == "__main__":
    asyncio.run(main())
