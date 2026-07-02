from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .html_parser import (
    parse_html,
    get_element_by_selector,
)
from .classifier import classify
from .descriptors import build_descriptor
from .template_engine import (
    render_com,
    render_pom,
    render_tests,
    PageModel,
    ComReference,
)
from .page_fetcher import fetch_page_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="testradius",
        description="TestRadius Workbench — COM/POM generation engine",
    )
    sub = parser.add_subparsers(dest="command")

    com_gen = sub.add_parser("com-gen", help="Generate a Component Object Model from a URL + CSS selector")
    com_gen.add_argument("url", help="URL of the page to analyze")
    com_gen.add_argument("selector", help="CSS selector for the target element")
    com_gen.add_argument("--output", "-o", help="Output file (default: stdout)")

    generate = sub.add_parser("generate", help="Generate full test suite from a URL")
    generate.add_argument("url", help="URL of the page to analyze")
    generate.add_argument("--output-dir", "-o", default=".", help="Output directory")
    generate.add_argument("--name", "-n", help="Test suite name (default: from page title)")

    return parser


async def com_gen(url: str, selector: str) -> str:
    html = await fetch_page_html(url)
    tree = parse_html(html, url=url)

    element = get_element_by_selector(tree, selector)
    if element is None:
        available = list(tree.elements_by_selector.keys())[:20]
        msg = f"Selector '{selector}' not found. Available selectors: {available}"
        raise LookupError(msg)

    classification = classify(element)
    descriptor = build_descriptor(element, classification)
    return render_com(descriptor)


def _find_significant_components(tree, max_components: int = 8):
    results = []
    seen_selectors: set[str] = set()

    def walk(element):
        if len(results) >= max_components:
            return
        classification = classify(element)
        if classification.confidence > 0 and classification.component_type != "GenericComponent":
            sel = element.css_path
            if sel not in seen_selectors:
                seen_selectors.add(sel)
                results.append((element, classification))
        for child in element.children:
            walk(child)

    walk(tree.root)
    return results


def _sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)


async def generate(url: str, output_dir: str, name: str | None = None) -> dict[str, str]:
    html = await fetch_page_html(url)
    tree = parse_html(html, url=url)

    page_title = ""
    for sel, elem in tree.elements_by_selector.items():
        if elem.tag == "title" and elem.text:
            page_title = elem.text
            break

    suite_name = name or _sanitize_filename(page_title) or "GeneratedSuite"
    suite_name = _sanitize_filename(suite_name)

    components = _find_significant_components(tree)

    com_refs: list[ComReference] = []
    com_files: dict[str, str] = {}

    for element, classification in components:
        descriptor = build_descriptor(element, classification)
        com_code = render_com(descriptor)
        file_name = f"{descriptor.class_name}.py"
        com_files[file_name] = com_code

        com_refs.append(
            ComReference(
                name=descriptor.class_name[0].lower() + descriptor.class_name[1:],
                class_name=descriptor.class_name,
                selector=descriptor.root_selector,
                has_test_actions=len(descriptor.fields) > 0,
            )
        )

    page_model = PageModel(
        class_name=suite_name,
        description=page_title or suite_name,
        components=com_refs,
        url=url,
    )

    pom_code = render_pom(page_model)
    test_code = render_tests(page_model)

    output_dir = str(Path(output_dir) / suite_name)

    result: dict[str, str] = {}
    result[f"{suite_name}.py"] = pom_code
    result[f"test_{suite_name}.py"] = test_code
    for fname, code in com_files.items():
        result[fname] = code

    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "com-gen":
        try:
            output = asyncio.run(com_gen(args.url, args.selector))
        except LookupError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Written to {args.output}")
        else:
            print(output)
        return 0

    if args.command == "generate":
        try:
            files = asyncio.run(generate(args.url, args.output_dir, args.name))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        output_path = Path(args.output_dir)
        suite_name = next(iter(files.keys())).replace(".py", "")
        output_path = output_path / suite_name
        output_path.mkdir(parents=True, exist_ok=True)

        for fname, code in files.items():
            file_path = output_path / fname
            file_path.write_text(code)
            print(f"  Created {file_path}")

        print(f"Generated {len(files)} files in {output_path}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
