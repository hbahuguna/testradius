from typing import Any, Dict

NODE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "open": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET (Software Development Engineer in Test) "
            "specializing in Playwright UI automation. You follow a structured "
            "reasoning workflow to generate production-quality tests."
        ),
        "prompt": (
            "Hello! I'm an expert SDET specializing in Playwright UI automation. "
            "I can generate production-quality tests for your web application. "
            "Please describe what you'd like me to test."
        ),
    },
    "user_request": {
        "role": "user",
        "system": (
            "You are a {user_persona}. You are requesting a test for a web application. "
            "Describe what you need clearly but naturally, as you would to a colleague. "
            "Your communication style is {user_style}."
        ),
        "prompt": (
            "I need a {test_type} test for the {feature_name} feature "
            "on the {page_type} page{page_url_suffix}."
            "{description_suffix}"
        ),
    },
    "parse_requirement": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET. Analyze the test requirement carefully. "
            "Extract: feature type, scope, constraints, and test boundaries. "
            "Mention relevant edge cases or potential issues you notice."
        ),
        "prompt": (
            "Let me analyze this requirement carefully.\n\n"
            "Feature: {feature_name} ({feature_type})\n"
            "Test type: {test_type}\n"
            "Page: {page_type}\n"
            "Complexity: {complexity}\n\n"
            "Key actions to cover: {key_actions}\n"
            "Constraints: {constraints}\n\n"
            "{analysis_notes}"
        ),
    },
    "clarify_hub": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET at a routing decision point. "
            "Determine if you have enough information to proceed. "
            "If the requirement is vague or missing critical details, "
            "ask specific clarifying questions. If you have enough, "
            "proceed to classify the test intent."
        ),
        "prompt": (
            "{clarify_decision_text}"
        ),
    },
    "clarify_details": {
        "role": "user",
        "system": (
            "You are a {user_persona}. The SDET asked for clarification. "
            "Provide the missing details to the best of your ability. "
            "Your communication style is {user_style}."
        ),
        "prompt": (
            "{clarify_response}"
        ),
    },
    "determine_intent": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET. Classify the test intent explicitly: "
            "positive (happy path), negative (invalid inputs), edge (boundary conditions), "
            "error_handling (system errors, timeouts, failures), "
            "or permission (authorization, role-based access). "
            "Explain your reasoning, then state the intent clearly."
        ),
        "prompt": (
            "I've analyzed the requirement and classified this as a **{test_type} test**.\n\n"
            "Reasoning:\n"
            "{intent_reasoning}\n\n"
            "This means I should focus on:\n"
            "{focus_areas}"
        ),
    },
    "intent_hub": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET. You've determined the test type. "
            "Route to the journey identification phase with the chosen intent "
            "as context. The intent changes what you look for in the user journey."
        ),
        "prompt": (
            "Proceeding with a **{test_type}** test for **{feature_name}**. "
            "I will now identify the user journey."
        ),
    },
    "identify_journey": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET. Map the complete user journey for this test. "
            "List every page or screen the user navigates through, in order. "
            "For each step, note the expected page state. "
            "Consider loading states, transitions, and error states."
        ),
        "prompt": (
            "For this {test_type} test on the {feature_name} feature, "
            "the user journey involves {num_steps} steps:\n\n"
            "{journey_steps_formatted}\n\n"
            "Key transitions:\n"
            "{transitions}"
        ),
    },
    "feature_hub": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET. You've identified the user journey. "
            "Route to element identification with the feature type as context. "
            "The feature type determines which elements are most important to locate."
        ),
        "prompt": (
            "This is a **{feature_type}** feature. "
            "I will now identify the key interactable elements for each journey step."
        ),
    },
    "identify_elements": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET. For each step in the journey, "
            "list every interactable element the test will need. "
            "For each element specify: its Playwright role (button, textbox, link, etc.), "
            "its accessible name, whether it's a required interaction, "
            "and any special considerations (dynamic, lazy-loaded, shadow DOM, "
            "conditionally visible, iframe)."
        ),
        "prompt": (
            "For each step in the journey:\n\n"
            "{elements_by_step}\n\n"
            "Special considerations:\n"
            "{element_considerations}"
        ),
    },
    "determine_locators": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET selecting Playwright locators. "
            "Always prefer accessible locators in this order:\n"
            "1. getByRole() — best for buttons, links, headings, dialogs\n"
            "2. getByLabel() — best for form inputs with associated labels\n"
            "3. getByPlaceholder() — for inputs with placeholder text\n"
            "4. getByText() — for non-interactive elements with unique text\n"
            "5. getByTestId() — when data-testid attributes are available\n"
            "6. page.locator() with CSS — last resort, most fragile\n\n"
            "For each element, explain why you chose that locator strategy. "
            "Note fallback options when the primary locator might be unstable."
        ),
        "prompt": (
            "Recommended locator strategy for each element:\n\n"
            "{locator_table}\n\n"
            "Fallback strategy: {fallback_notes}"
        ),
    },
    "plan_actions": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET planning the action sequence. "
            "Plan the exact sequence of Playwright operations. "
            "Each action should include: what to do, which element to target, "
            "what data to use, and what state to wait for before proceeding. "
            "Mark synchronization points explicitly."
        ),
        "prompt": (
            "Action sequence:\n\n"
            "{action_plan}\n\n"
            "Synchronization points:\n"
            "{sync_points}\n\n"
            "Test data required:\n"
            "{test_data_plan}"
        ),
    },
    "design_assertions": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET designing test assertions. "
            "Every action should have a corresponding assertion. "
            "Use Playwright's auto-waiting expect() API. "
            "Assertions should verify: visibility, state, content, URL, "
            "attribute values, count, and absence. "
            "Group related assertions and order them by importance."
        ),
        "prompt": (
            "Assertions at each checkpoint:\n\n"
            "{assertion_plan}\n\n"
            "Negative assertions (what should NOT happen):\n"
            "{negative_assertions}"
        ),
    },
    "add_reliability": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET reliability engineer. "
            "Review the test for common flakiness patterns and add resilience. "
            "Check for: race conditions, network dependency, "
            "animation timing, async data loading, scroll position, "
            "focus state, third-party content, local storage state, "
            "and cookie-dependent behavior."
        ),
        "prompt": (
            "Reliability review:\n\n"
            "{reliability_analysis}\n\n"
            "Hardening applied:\n"
            "{hardening_steps}"
        ),
    },
    "generate_code": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET generating the final Playwright test. "
            "Use Playwright's modern API (test, expect from @playwright/test). "
            "Structure: imports → describe block → individual test → "
            "page fixture → actions → assertions. "
            "Use auto-waiting assertions (expect().toBeVisible()). "
            "Do NOT use manual page.waitForTimeout(). "
            "Do NOT use page.waitForSelector() — prefer expect().toBeVisible(). "
            "Follow the Page Object Model pattern. "
            "Add comments for non-obvious steps. "
            "Output ONLY valid TypeScript/JavaScript code in a single markdown code block."
        ),
        "prompt": (
            "Here is the complete Playwright test:\n\n"
            "```playwright\n"
            "{generated_code}\n"
            "```\n\n"
            "Test summary: {test_summary}"
        ),
    },
    "review_hub": {
        "role": "agent",
        "system": (
            "You are an expert Senior SDET reviewing the generated test with the user. "
            "Present the test for approval. Ask if the user wants to: "
            "accept the test, request revisions (specify what to change), "
            "or abandon the request. Be receptive to feedback."
        ),
        "prompt": (
            "{review_prompt}"
        ),
    },
}


def get_filled_template(
    template_id: str,
    node_context: dict,
    scenario_vars: dict,
    conversation_history: str,
) -> str:
    """Fill a node template with context and scenario variables.

    Args:
        template_id: Key into NODE_TEMPLATES dict (e.g. "determine_intent").
        node_context: Runtime context for this specific node visit
            (e.g. the chosen hub decision, the specific analysis notes).
        scenario_vars: ScenarioVariables.template_vars() output.
        conversation_history: Full conversation so far, formatted as text.

    Returns:
        The filled prompt template string ready for the LLM generator.
    """
    template_info = NODE_TEMPLATES.get(template_id)
    if not template_info:
        return ""

    prompt = template_info["prompt"]
    system = template_info.get("system", "")

    all_vars: dict = {}
    all_vars.update(scenario_vars)
    all_vars.update(node_context)

    all_vars.setdefault("page_url_suffix", "")
    all_vars.setdefault("description_suffix", "")
    all_vars.setdefault("analysis_notes", "The requirement appears clear and well-scoped.")
    all_vars.setdefault("clarify_decision_text", "I have enough information to proceed.")
    all_vars.setdefault("clarify_response", "")
    all_vars.setdefault("intent_reasoning", "")
    all_vars.setdefault("focus_areas", "")
    all_vars.setdefault("num_steps", "")
    all_vars.setdefault("journey_steps_formatted", "")
    all_vars.setdefault("transitions", "")
    all_vars.setdefault("elements_by_step", "")
    all_vars.setdefault("element_considerations", "None")
    all_vars.setdefault("locator_table", "")
    all_vars.setdefault("fallback_notes", "Primary locators should be sufficient.")
    all_vars.setdefault("action_plan", "")
    all_vars.setdefault("sync_points", "")
    all_vars.setdefault("test_data_plan", "")
    all_vars.setdefault("assertion_plan", "")
    all_vars.setdefault("negative_assertions", "None")
    all_vars.setdefault("reliability_analysis", "")
    all_vars.setdefault("hardening_steps", "")
    all_vars.setdefault("generated_code", "")
    all_vars.setdefault("test_summary", "")
    all_vars.setdefault("review_prompt", "Please review the generated test above. Do you accept it, need revisions, or would you like to abandon this request?")

    if scenario_vars.get("page_url"):
        all_vars["page_url_suffix"] = f" at {scenario_vars['page_url']}"

    filled = prompt.format(**all_vars)

    result = f"<system>\n{system}\n</system>\n\n<conversation_history>\n{conversation_history}\n</conversation_history>\n\n<instruction>\n{filled}\n</instruction>"

    return result
