import asyncio
import json
import argparse
import sys
from .engine import DiscoveryEngine
from .probes.dependency import DependencyProbe
from .probes.heuristic import HeuristicProbe
from .probes.code import CodeSignatureProbe

async def discover(path: str):
    probes = [
        DependencyProbe(),
        HeuristicProbe(),
        CodeSignatureProbe(),
    ]
    engine = DiscoveryEngine(probes)
    result = await engine.discover(path)
    return result

def main():
    parser = argparse.ArgumentParser(description="TestSquad Static Analysis Discovery")
    parser.add_argument("path", nargs="?", default=".", help="Path to the repository root")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    
    args = parser.parse_args()
    
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(discover(args.path))
    
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(f"Primary Language: {result.primary_language.value}")
        print(f"Repo Structure: {result.repo_structure}")
        print("\nDetected Frameworks/Tools:")
        for res in result.detected_frameworks:
            print(f"- {res.label.value} (Confidence: {res.confidence:.2f}, Source: {res.source})")

if __name__ == "__main__":
    main()
