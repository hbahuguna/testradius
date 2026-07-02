from __future__ import annotations

import argparse
import asyncio
import json
import sys


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SDET Playwright Test Generator — scrape a page and generate tests via fine-tuned model",
    )
    sub = p.add_subparsers(dest="command", required=True)

    scrape = sub.add_parser("scrape", help="Scrape a page and save snapshot")
    scrape.add_argument("url", help="URL to scrape")
    scrape.add_argument("--output", "-o", default="page_snapshot.json", help="Output path")
    scrape.add_argument("--wait", type=int, default=30, help="Timeout in seconds")
    scrape.add_argument("--viewport", default="1280x720", help="Viewport WxH")
    scrape.add_argument("--auth-cookies", help="JSON file with auth cookies")

    gen = sub.add_parser("generate", help="Generate test from page snapshot")
    gen.add_argument("scenario", help="Test scenario description")
    gen.add_argument("--snapshot", "-s", default="page_snapshot.json", help="Page snapshot JSON")
    gen.add_argument("--model", "-m", required=True, help="Trained LoRA adapter path")
    gen.add_argument("--base-model", default="Qwen/Qwen3-8B", help="Base model name")
    gen.add_argument("--max-tokens", type=int, default=2048, help="Max generation tokens")
    gen.add_argument("--temperature", type=float, default=0.7, help="Sampling temperature")

    full = sub.add_parser("run", help="Scrape + generate in one command")
    full.add_argument("url", help="URL to scrape and test")
    full.add_argument("scenario", help="Test scenario description")
    full.add_argument("--model", "-m", required=True, help="Trained LoRA adapter path")
    full.add_argument("--base-model", default="Qwen/Qwen3-8B")
    full.add_argument("--output", "-o", help="Save generated test to file")
    full.add_argument("--wait", type=int, default=30)
    full.add_argument("--max-tokens", type=int, default=2048)
    full.add_argument("--temperature", type=float, default=0.7)

    return p


async def _cmd_scrape(args: argparse.Namespace) -> None:
    from testsquad_workbench.sdet_procedure.inference.page_scraper import PageScraper

    parts = [int(x) for x in args.viewport.split("x")]
    viewport = {"width": parts[0], "height": parts[1]} if len(parts) == 2 else None

    auth_cookies = None
    if args.auth_cookies:
        with open(args.auth_cookies) as f:
            auth_cookies = json.load(f)

    async with PageScraper(viewport=viewport, timeout_ms=args.wait * 1000) as scraper:
        snapshot = await scraper.scrape(args.url, auth_cookies=auth_cookies)

    with open(args.output, "w") as f:
        json.dump(snapshot.to_dict(), f, indent=2)
    print(f"Saved page snapshot to {args.output}")
    print(f"  Title: {snapshot.title}")
    print(f"  Interactive elements: {len(snapshot.elements)}")


def _cmd_generate(args: argparse.Namespace) -> None:
    from testsquad_workbench.sdet_procedure.inference.inference import (
        SDETInference,
        InferenceConfig,
    )
    from testsquad_workbench.sdet_procedure.inference.page_scraper import PageSnapshot, InteractiveElement

    with open(args.snapshot) as f:
        data = json.load(f)

    snapshot = PageSnapshot(
        url=data["url"],
        title=data.get("title", ""),
        elements=[InteractiveElement(**el) for el in data.get("elements", [])],
        a11y_tree=data.get("a11y_tree"),
        viewport=data.get("viewport"),
    )

    config = InferenceConfig(
        model_path=args.model,
        base_model_name=args.base_model,
        max_new_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    engine = SDETInference(config)
    engine.load()
    result = engine.generate(scenario=args.scenario, page_snapshot=snapshot)
    print(result)


async def _cmd_run(args: argparse.Namespace) -> None:
    from testsquad_workbench.sdet_procedure.inference.page_scraper import PageScraper
    from testsquad_workbench.sdet_procedure.inference.inference import (
        SDETInference,
        InferenceConfig,
    )

    async with PageScraper(timeout_ms=args.wait * 1000) as scraper:
        snapshot = await scraper.scrape(args.url)

    print(f"Scraped: {snapshot.title} ({len(snapshot.elements)} elements)")

    config = InferenceConfig(
        model_path=args.model,
        base_model_name=args.base_model,
        max_new_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    engine = SDETInference(config)
    engine.load()
    result = engine.generate(scenario=args.scenario, page_snapshot=snapshot)

    if args.output:
        with open(args.output, "w") as f:
            f.write(result)
        print(f"Saved generated test to {args.output}")
    else:
        print(result)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "scrape":
        asyncio.run(_cmd_scrape(args))
    elif args.command == "generate":
        _cmd_generate(args)
    elif args.command == "run":
        asyncio.run(_cmd_run(args))


if __name__ == "__main__":
    main()
