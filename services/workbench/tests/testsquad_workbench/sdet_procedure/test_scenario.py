import pytest

from testsquad_workbench.sdet_procedure.scenario import (
    FeatureType,
    TestType,
    PageType,
    UserStyle,
    Complexity,
    ScenarioVariables,
    ScenarioSampler,
    generate_description,
)


class TestEnums:
    def test_feature_type_values(self):
        assert FeatureType.AUTH.value == "auth"
        assert FeatureType.FORM.value == "form"
        assert FeatureType.CRUD.value == "crud"
        assert len(list(FeatureType)) == 9

    def test_test_type_values(self):
        assert TestType.POSITIVE.value == "positive"
        assert TestType.NEGATIVE.value == "negative"
        assert TestType.EDGE.value == "edge"
        assert TestType.ERROR_HANDLING.value == "error_handling"
        assert TestType.PERMISSION.value == "permission"
        assert len(list(TestType)) == 5

    def test_page_type_values(self):
        assert PageType.SINGLE_PAGE.value == "single_page"
        assert PageType.DASHBOARD.value == "dashboard"
        assert len(list(PageType)) == 6

    def test_user_style_values(self):
        assert UserStyle.SPECIFIC.value == "specific"
        assert UserStyle.VAGUE.value == "vague"
        assert UserStyle.UNCERTAIN.value == "uncertain"
        assert UserStyle.EXPERT.value == "expert"
        assert UserStyle.NOVICE.value == "novice"
        assert len(list(UserStyle)) == 5

    def test_complexity_values(self):
        assert Complexity.SIMPLE.value == "simple"
        assert Complexity.MODERATE.value == "moderate"
        assert Complexity.COMPLEX.value == "complex"
        assert len(list(Complexity)) == 3


class TestScenarioVariables:
    def test_to_dict_returns_all_keys(self):
        sv = ScenarioVariables(
            feature_type=FeatureType.AUTH,
            test_type=TestType.POSITIVE,
            page_type=PageType.SINGLE_PAGE,
            user_style=UserStyle.SPECIFIC,
            complexity=Complexity.SIMPLE,
        )
        d = sv.to_dict()
        assert d["feature_type"] == "auth"
        assert d["test_type"] == "positive"
        assert d["page_type"] == "single_page"

    def test_template_vars_formats_page_type(self):
        sv = ScenarioVariables(
            feature_type=FeatureType.FORM,
            test_type=TestType.NEGATIVE,
            page_type=PageType.MULTI_PAGE,
            user_style=UserStyle.EXPERT,
            complexity=Complexity.MODERATE,
        )
        t = sv.template_vars()
        assert t["page_type"] == "multi page"
        assert t["feature_type"] == "form"
        assert t["test_type"] == "negative"

    def test_template_vars_joins_key_actions(self):
        sv = ScenarioVariables(
            feature_type=FeatureType.AUTH,
            test_type=TestType.POSITIVE,
            page_type=PageType.SINGLE_PAGE,
            user_style=UserStyle.SPECIFIC,
            complexity=Complexity.SIMPLE,
            key_actions=["click", "verify", "submit"],
        )
        t = sv.template_vars()
        assert "click; verify; submit" in t["key_actions"]

    def test_template_vars_no_constraints(self):
        sv = ScenarioVariables(
            feature_type=FeatureType.AUTH,
            test_type=TestType.POSITIVE,
            page_type=PageType.SINGLE_PAGE,
            user_style=UserStyle.SPECIFIC,
            complexity=Complexity.SIMPLE,
        )
        t = sv.template_vars()
        assert t["constraints"] == "None"


class TestScenarioSampler:
    def test_sample_returns_scenario(self):
        sampler = ScenarioSampler(seed=42)
        sv = sampler.sample()
        assert isinstance(sv, ScenarioVariables)
        assert isinstance(sv.feature_type, FeatureType)
        assert isinstance(sv.test_type, TestType)
        assert isinstance(sv.page_type, PageType)
        assert isinstance(sv.user_style, UserStyle)
        assert isinstance(sv.complexity, Complexity)

    def test_sample_fills_all_fields(self):
        sampler = ScenarioSampler(seed=42)
        sv = sampler.sample()
        assert sv.feature_name
        assert sv.page_url
        assert sv.key_actions
        assert sv.user_persona
        assert sv.description
        assert isinstance(sv.test_data, dict)
        assert isinstance(sv.constraints, list)

    def test_sample_is_deterministic(self):
        s1 = ScenarioSampler(seed=42).sample()
        s2 = ScenarioSampler(seed=42).sample()
        assert s1.feature_type == s2.feature_type
        assert s1.test_type == s2.test_type
        assert s1.feature_name == s2.feature_name

    def test_different_seeds_give_different_scenarios(self):
        s1 = ScenarioSampler(seed=1).sample()
        s2 = ScenarioSampler(seed=999).sample()
        assert (s1.feature_type != s2.feature_type or
                s1.test_type != s2.test_type or
                s1.feature_name != s2.feature_name)

    def test_sample_n_returns_n_scenarios(self):
        sampler = ScenarioSampler(seed=42)
        scenarios = sampler.sample_n(5)
        assert len(scenarios) == 5
        assert all(isinstance(s, ScenarioVariables) for s in scenarios)

    def test_sample_by_feature_uses_correct_feature(self):
        sampler = ScenarioSampler(seed=42)
        scenarios = sampler.sample_by_feature(FeatureType.PAYMENT, 3)
        assert len(scenarios) == 3
        for s in scenarios:
            assert s.feature_type == FeatureType.PAYMENT
            assert s.page_url.startswith("https://store.example.com/") or \
                   s.page_url.startswith("https://app.example.com/billing")

    def test_description_contains_feature_name(self):
        sampler = ScenarioSampler(seed=42)
        sv = sampler.sample()
        assert sv.feature_name in sv.description or \
               sv.feature_type.value in sv.description

    def test_complexity_affects_constraint_count(self):
        sampler = ScenarioSampler(seed=42)
        simple_count = len(sampler._sample_constraints(FeatureType.AUTH, Complexity.SIMPLE))
        complex_count = len(sampler._sample_constraints(FeatureType.AUTH, Complexity.COMPLEX))
        assert simple_count <= complex_count


class TestGenerateDescription:
    def test_description_includes_test_type(self):
        sv = ScenarioVariables(
            feature_type=FeatureType.AUTH,
            test_type=TestType.POSITIVE,
            page_type=PageType.SINGLE_PAGE,
            user_style=UserStyle.SPECIFIC,
            complexity=Complexity.SIMPLE,
            feature_name="Login Form",
            page_url="https://app.example.com/login",
        )
        desc = generate_description(sv)
        assert "positive" in desc
        assert "Login Form" in desc
        assert "single page" in desc
