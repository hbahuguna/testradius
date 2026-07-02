import pytest

from testsquad_workbench.generation.cli import build_parser, main


class TestCli:
    def test_parser_com_gen(self):
        parser = build_parser()
        args = parser.parse_args(["com-gen", "http://example.com", "form"])
        assert args.command == "com-gen"
        assert args.url == "http://example.com"
        assert args.selector == "form"

    def test_parser_com_gen_with_output(self):
        parser = build_parser()
        args = parser.parse_args(
            ["com-gen", "http://example.com", "form", "-o", "login.py"]
        )
        assert args.output == "login.py"

    def test_parser_generate(self):
        parser = build_parser()
        args = parser.parse_args(["generate", "http://example.com"])
        assert args.command == "generate"
        assert args.url == "http://example.com"

    def test_parser_generate_with_options(self):
        parser = build_parser()
        args = parser.parse_args(
            ["generate", "http://example.com", "-o", "./tests", "-n", "login_flow"]
        )
        assert args.output_dir == "./tests"
        assert args.name == "login_flow"

    def test_main_no_command_shows_help(self):
        result = main([])
        assert result == 0

    def test_main_unknown_command(self):
        result = main(["unknown"])
        assert result == 2

    def test_main_com_gen_no_url_raises(self):
        result = main(["com-gen"])
        assert result == 2

    def test_main_com_gen_nonexistent_selector(self):
        result = main(["com-gen", "file:///nonexistent.html", "div"])
        assert result == 1
