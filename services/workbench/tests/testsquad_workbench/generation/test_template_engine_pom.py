import pytest

from testsquad_workbench.generation.template_engine import (
    render_pom,
    render_tests,
    PageModel,
    ComReference,
)


class TestRenderPom:
    def test_renders_pom_class(self):
        model = PageModel(
            class_name="LoginPage",
            description="Login page",
            components=[
                ComReference(
                    name="login_form",
                    class_name="LoginForm",
                    selector="[data-testid='login-form']",
                ),
            ],
        )
        output = render_pom(model)
        assert "class LoginPage:" in output
        assert "LoginForm" in output
        assert "login_form" in output

    def test_renders_multiple_components(self):
        model = PageModel(
            class_name="DashboardPage",
            description="Dashboard page",
            components=[
                ComReference(name="navbar", class_name="NavBar", selector="nav"),
                ComReference(name="sidebar", class_name="Sidebar", selector="aside"),
            ],
        )
        output = render_pom(model)
        assert "self.navbar = NavBar" in output
        assert "self.sidebar = Sidebar" in output

    def test_renders_navigate(self):
        model = PageModel(
            class_name="HomePage",
            description="Home page",
            components=[],
        )
        output = render_pom(model)
        assert "def navigate" in output
        assert "is_loaded" in output

    def test_renders_com_imports(self):
        model = PageModel(
            class_name="LoginPage",
            description="Login page",
            components=[
                ComReference(name="form", class_name="LoginForm", selector="#form"),
                ComReference(name="nav", class_name="NavBar", selector="nav"),
            ],
        )
        output = render_pom(model)
        assert "from .LoginForm import LoginForm" in output
        assert "from .NavBar import NavBar" in output


class TestRenderTests:
    def test_renders_test_class(self):
        model = PageModel(
            class_name="LoginPage",
            description="Login page",
            components=[
                ComReference(name="form", class_name="LoginForm", selector="#form"),
            ],
        )
        output = render_tests(model)
        assert "class TestLoginPage:" in output
        assert "test_page_loads" in output
        assert "test_component_visibility" in output

    def test_renders_component_checks(self):
        model = PageModel(
            class_name="DashboardPage",
            description="Dashboard page",
            components=[
                ComReference(name="navbar", class_name="NavBar", selector="nav"),
            ],
        )
        output = render_tests(model)
        assert "pom.navbar.is_loaded" in output

    def test_empty_components(self):
        model = PageModel(
            class_name="EmptyPage",
            description="Empty page",
            components=[],
        )
        output = render_tests(model)
        assert "class TestEmptyPage:" in output
        assert "test_page_loads" in output
