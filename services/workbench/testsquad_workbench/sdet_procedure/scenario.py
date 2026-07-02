from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Tuple

if TYPE_CHECKING:
    from testsquad_workbench.sdet_procedure.graph import Path


class FeatureType(str, Enum):
    AUTH = "auth"
    FORM = "form"
    CRUD = "crud"
    NAVIGATION = "navigation"
    DATA_DISPLAY = "data_display"
    SEARCH = "search"
    PAYMENT = "payment"
    NOTIFICATION = "notification"
    MEDIA = "media"


class TestType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    EDGE = "edge"
    ERROR_HANDLING = "error_handling"
    PERMISSION = "permission"


class PageType(str, Enum):
    SINGLE_PAGE = "single_page"
    MULTI_PAGE = "multi_page"
    MODAL_FLOW = "modal_flow"
    WIZARD = "wizard"
    DASHBOARD = "dashboard"
    SETTINGS = "settings"


class UserStyle(str, Enum):
    SPECIFIC = "specific"
    VAGUE = "vague"
    UNCERTAIN = "uncertain"
    EXPERT = "expert"
    NOVICE = "novice"


class Complexity(str, Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


@dataclass
class ScenarioVariables:
    feature_type: FeatureType
    test_type: TestType
    page_type: PageType
    user_style: UserStyle
    complexity: Complexity
    feature_name: str = ""
    page_url: str = ""
    key_actions: List[str] = field(default_factory=list)
    test_data: Dict[str, Any] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    user_persona: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_type": self.feature_type.value,
            "test_type": self.test_type.value,
            "page_type": self.page_type.value,
            "user_style": self.user_style.value,
            "complexity": self.complexity.value,
            "feature_name": self.feature_name,
            "page_url": self.page_url,
            "key_actions": self.key_actions,
            "test_data": self.test_data,
            "constraints": self.constraints,
            "user_persona": self.user_persona,
            "description": self.description,
        }

    def template_vars(self) -> Dict[str, str]:
        return {
            "feature_type": self.feature_type.value,
            "test_type": self.test_type.value,
            "page_type": self.page_type.value.replace("_", " "),
            "user_style": self.user_style.value,
            "complexity": self.complexity.value,
            "feature_name": self.feature_name,
            "page_url": self.page_url,
            "key_actions": "; ".join(self.key_actions),
            "constraints": "; ".join(self.constraints) if self.constraints else "None",
            "user_persona": self.user_persona,
            "description": self.description,
        }


_FEATURE_NAMES: Dict[FeatureType, List[str]] = {
    FeatureType.AUTH: [
        "Login Form",
        "Registration Form",
        "Password Reset Flow",
        "Two-Factor Authentication",
        "OAuth Social Login",
        "Session Management",
    ],
    FeatureType.FORM: [
        "Contact Us Form",
        "Feedback Form",
        "Profile Edit Form",
        "Survey Form",
        "Newsletter Signup",
        "Multi-Step Wizard",
    ],
    FeatureType.CRUD: [
        "User Management Table",
        "Product Catalog",
        "Order Management",
        "Inventory List",
        "Task Board",
        "Document Library",
    ],
    FeatureType.NAVIGATION: [
        "Main Navigation Menu",
        "Breadcrumb Trail",
        "Sidebar Menu",
        "Tab Navigation",
        "Pagination Controls",
        "Dropdown Menu",
    ],
    FeatureType.DATA_DISPLAY: [
        "Dashboard Widgets",
        "Analytics Charts",
        "Data Table with Filters",
        "Activity Feed",
        "Notification Center",
        "Calendar View",
    ],
    FeatureType.SEARCH: [
        "Global Search Bar",
        "Advanced Search Filters",
        "Search Autocomplete",
        "Search Results Page",
        "Voice Search",
    ],
    FeatureType.PAYMENT: [
        "Checkout Page",
        "Payment Form",
        "Subscription Management",
        "Invoice Payment",
        "Refund Processing",
    ],
    FeatureType.NOTIFICATION: [
        "Push Notification Settings",
        "Email Notification Preferences",
        "In-App Toast Alerts",
        "SMS Notification Setup",
    ],
    FeatureType.MEDIA: [
        "Image Gallery",
        "Video Player",
        "File Uploader",
        "Drag-and-Drop Media Library",
        "Audio Player",
    ],
}

_PAGE_URLS: Dict[FeatureType, List[str]] = {
    FeatureType.AUTH: [
        "https://app.example.com/login",
        "https://app.example.com/register",
        "https://app.example.com/forgot-password",
    ],
    FeatureType.FORM: [
        "https://app.example.com/contact",
        "https://app.example.com/settings/profile",
        "https://app.example.com/survey/new",
    ],
    FeatureType.CRUD: [
        "https://admin.example.com/users",
        "https://admin.example.com/products",
        "https://admin.example.com/orders",
    ],
    FeatureType.NAVIGATION: [
        "https://app.example.com/dashboard",
        "https://app.example.com/settings",
    ],
    FeatureType.DATA_DISPLAY: [
        "https://app.example.com/dashboard",
        "https://app.example.com/analytics",
        "https://app.example.com/activity",
    ],
    FeatureType.SEARCH: [
        "https://app.example.com/search",
        "https://store.example.com/search",
    ],
    FeatureType.PAYMENT: [
        "https://store.example.com/checkout",
        "https://app.example.com/billing",
    ],
    FeatureType.NOTIFICATION: [
        "https://app.example.com/settings/notifications",
        "https://app.example.com/notifications",
    ],
    FeatureType.MEDIA: [
        "https://app.example.com/gallery",
        "https://app.example.com/media/upload",
    ],
}

_KEY_ACTIONS: Dict[FeatureType, List[str]] = {
    FeatureType.AUTH: [
        "Enter username/email",
        "Enter password",
        "Click sign-in button",
        "Verify redirect to dashboard",
        "Check error message for invalid credentials",
    ],
    FeatureType.FORM: [
        "Fill in text fields",
        "Select dropdown options",
        "Upload a file",
        "Submit form",
        "Verify success confirmation",
    ],
    FeatureType.CRUD: [
        "Navigate to list view",
        "Click create new button",
        "Fill in creation form",
        "Submit and verify item appears",
        "Edit existing item",
        "Delete item and verify removal",
    ],
    FeatureType.NAVIGATION: [
        "Click menu item",
        "Verify page transition",
        "Check active state on current item",
        "Navigate using breadcrumbs",
        "Verify URL updates correctly",
    ],
    FeatureType.DATA_DISPLAY: [
        "Load page with data",
        "Apply filter",
        "Sort by column",
        "Click on data item",
        "Verify detail view opens",
    ],
    FeatureType.SEARCH: [
        "Type search query",
        "View autocomplete suggestions",
        "Submit search",
        "Verify results appear",
        "Apply search filters",
    ],
    FeatureType.PAYMENT: [
        "Review cart items",
        "Enter shipping details",
        "Enter payment information",
        "Confirm purchase",
        "Verify order confirmation",
    ],
    FeatureType.NOTIFICATION: [
        "Toggle notification type",
        "Set preference level",
        "Save settings",
        "Verify confirmation toast",
        "Test that preference persists after reload",
    ],
    FeatureType.MEDIA: [
        "Browse media items",
        "Click to view full size",
        "Upload new file",
        "Drag to reorder",
        "Delete media item",
    ],
}

_USER_PERSONAS: Dict[UserStyle, List[str]] = {
    UserStyle.SPECIFIC: [
        "QA engineer writing regression tests",
        "Developer adding coverage for a new feature",
        "Test lead performing release validation",
    ],
    UserStyle.VAGUE: [
        "Product manager checking if a feature works",
        "Non-technical stakeholder wanting basic coverage",
        "Junior developer unsure what to test",
    ],
    UserStyle.UNCERTAIN: [
        "New team member learning the codebase",
        "Contractor unfamiliar with the application",
        "Intern exploring testing patterns",
    ],
    UserStyle.EXPERT: [
        "Senior SDET writing comprehensive test suite",
        "Test architect designing test infrastructure",
        "Performance engineer setting up benchmarks",
    ],
    UserStyle.NOVICE: [
        "Junior QA learning test automation",
        "Bootcamp graduate writing first tests",
        "Manual tester transitioning to automation",
    ],
}


def generate_description(scenario: ScenarioVariables) -> str:
    """Generate a human-readable scenario description from variables."""
    parts = [
        f"A {scenario.test_type.value} test for the {scenario.feature_name or scenario.feature_type.value} feature",
    ]
    parts.append(f"on a {scenario.page_type.value.replace('_', ' ')} page")
    if scenario.page_url:
        parts.append(f"at {scenario.page_url}")
    parts.append(f"({scenario.complexity.value} complexity)")
    return " ".join(parts)


class ScenarioSampler:
    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def sample(self) -> ScenarioVariables:
        feature_type = self.rng.choice(list(FeatureType))
        return self._sample_with_feature(feature_type)

    def _sample_with_feature(self, feature_type: FeatureType) -> ScenarioVariables:
        test_type = self.rng.choice(list(TestType))
        page_type = self.rng.choice(list(PageType))
        user_style = self.rng.choice(list(UserStyle))
        complexity = self.rng.choice(list(Complexity))
        feature_name = self.rng.choice(_FEATURE_NAMES[feature_type])
        page_url = self.rng.choice(_PAGE_URLS[feature_type])

        num_actions = {
            Complexity.SIMPLE: (2, 4),
            Complexity.MODERATE: (4, 6),
            Complexity.COMPLEX: (6, 9),
        }[complexity]
        all_actions = _KEY_ACTIONS[feature_type]
        key_actions = self.rng.sample(
            all_actions, min(self.rng.randint(*num_actions), len(all_actions))
        )

        user_persona = self.rng.choice(_USER_PERSONAS[user_style])
        constraints = self._sample_constraints(feature_type, complexity)

        scenario = ScenarioVariables(
            feature_type=feature_type,
            test_type=test_type,
            page_type=page_type,
            user_style=user_style,
            complexity=complexity,
            feature_name=feature_name,
            page_url=page_url,
            key_actions=key_actions,
            constraints=constraints,
            user_persona=user_persona,
        )
        scenario.description = generate_description(scenario)
        return scenario

    def _sample_constraints(
        self, feature_type: FeatureType, complexity: Complexity
    ) -> List[str]:
        all_constraints = {
            "no_testid_attributes",
            "dynamic_class_names",
            "shadow_dom_components",
            "lazy_loaded_content",
            "requires_auth",
            "cross_origin_iframes",
            "rate_limited_endpoints",
            "no_accessible_labels",
            "infinite_scroll",
            "websocket_updates",
        }
        if complexity == Complexity.SIMPLE:
            count = self.rng.randint(0, 1)
        elif complexity == Complexity.MODERATE:
            count = self.rng.randint(1, 3)
        else:
            count = self.rng.randint(2, 5)
        chosen = self.rng.sample(list(all_constraints), min(count, len(all_constraints)))
        return chosen

    def sample_n(self, n: int) -> List[ScenarioVariables]:
        return [self.sample() for _ in range(n)]

    def sample_by_feature(
        self, feature_type: FeatureType, n: int
    ) -> List[ScenarioVariables]:
        return [self._sample_with_feature(feature_type) for _ in range(n)]

    def paired_scenarios(
        self,
        path: "Path",
        n: int = 60,
        seed: Optional[int] = None,
    ) -> Iterator[Tuple["Path", ScenarioVariables]]:
        path_rng = random.Random(seed)
        clarified = path.hub_decisions.get("N3", "") == "needs_clarification"
        revised = path.hub_decisions.get("N15", "") == "revise"

        for i in range(n):
            sc = self.sample()

            if clarified:
                if UserStyle.VAGUE in (sc.user_style, UserStyle.UNCERTAIN):
                    sc.user_style = UserStyle.VAGUE
                    sc.user_persona = path_rng.choice(_USER_PERSONAS[UserStyle.VAGUE])

            if revised:
                sc.test_type = TestType.EDGE if sc.test_type == TestType.POSITIVE else TestType.POSITIVE

            yield (path, sc)
