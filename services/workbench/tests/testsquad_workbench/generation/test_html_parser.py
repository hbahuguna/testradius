import pytest
from bs4 import BeautifulSoup

from testsquad_workbench.generation.html_parser import (
    parse_html,
    get_element_by_css,
    _compute_css_path,
    _compute_xpath,
    _extract_element_info,
)
from testsquad_workbench.generation.models import DOMTree


class TestParseHtml:
    def test_parse_simple_html(self):
        html = "<html><body><div id='main'><p>Hello</p></div></body></html>"
        tree = parse_html(html)
        assert isinstance(tree, DOMTree)
        assert tree.root.tag == "body"
        assert len(tree.root.children) == 1
        assert tree.root.children[0].tag == "div"
        assert tree.root.children[0].attributes.get("id") == "main"

    def test_extracts_text_content(self):
        html = "<html><body><p>Hello World</p></body></html>"
        tree = parse_html(html)
        p = tree.root.children[0]
        assert p.text == "Hello World"

    def test_identifies_interactive_elements(self):
        html = "<html><body><button>Click</button><a href='/'>Link</a><span>Text</span></body></html>"
        tree = parse_html(html)
        children = tree.root.children
        assert children[0].is_interactive is True
        assert children[1].is_interactive is True
        assert children[2].is_interactive is False

    def test_hidden_element_not_visible(self):
        html = "<html><body><div style='display:none'>Hidden</div><p>Visible</p></body></html>"
        tree = parse_html(html)
        children = tree.root.children
        assert children[0].is_visible is False
        assert children[1].is_visible is True

    def test_element_with_aria(self):
        html = "<html><body><button aria-label='Submit' role='button'>Go</button></body></html>"
        tree = parse_html(html)
        btn = tree.root.children[0]
        assert btn.aria.get("aria-label") == "Submit"
        assert btn.role == "button"

    def test_parse_with_roles_inherited(self):
        html = "<html><body><a href='/login'>Login</a></body></html>"
        tree = parse_html(html)
        link = tree.root.children[0]
        assert link.role == "link"
        assert link.is_interactive is True

    def test_css_path_generation(self):
        html = "<html><body><div class='container'><form id='login'><input type='email'/></form></div></body></html>"
        soup = BeautifulSoup(html, "lxml")
        input_tag = soup.find("input")
        css_path = _compute_css_path(input_tag)
        assert "input" in css_path

    def test_xpath_generation(self):
        html = "<html><body><div><p>First</p><p>Second</p></div></body></html>"
        soup = BeautifulSoup(html, "lxml")
        paragraphs = soup.find_all("p")
        xpath_second = _compute_xpath(paragraphs[1])
        assert "p[2]" in xpath_second

    def test_parse_empty_html(self):
        html = "<html><body></body></html>"
        tree = parse_html(html)
        assert tree.root.tag == "body"
        assert len(tree.root.children) == 0

    def test_nested_children_count(self):
        html = "<html><body><ul><li>A</li><li>B</li><li>C</li></ul></body></html>"
        tree = parse_html(html)
        ul = tree.root.children[0]
        assert ul.tag == "ul"
        assert len(ul.children) == 3
        assert [c.text for c in ul.children] == ["A", "B", "C"]

    def test_elements_by_selector_indexing(self):
        html = "<html><body><div id='a'><p id='b'>Text</p></div></body></html>"
        tree = parse_html(html)
        assert len(tree.elements_by_selector) > 0


class TestGetElementByCss:
    def test_get_by_exact_css(self):
        html = "<html><body><div class='card'><p>Content</p></div></body></html>"
        tree = parse_html(html)
        found = tree.elements_by_selector
        assert len(found) > 0

    def test_get_nonexistent_css(self):
        html = "<html><body><p>Hi</p></body></html>"
        tree = parse_html(html)
        result = get_element_by_css(tree, "div.nonexistent")
        assert result is None
