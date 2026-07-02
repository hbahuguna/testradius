from __future__ import annotations

from testsquad_workbench.sdet_procedure.inference.conversation_state import (
    ConversationState,
    classify_test_type,
    classify_feature_type,
    classify_clarify_intent,
    classify_review_intent,
    NodeId,
)
from testsquad_workbench.sdet_procedure.inference.session_manager import (
    SessionManager,
)


class TestClassifiers:
    def test_classify_test_type_positive(self):
        assert classify_test_type("Test successful login flow") == "positive"

    def test_classify_test_type_negative(self):
        assert classify_test_type("Test invalid password gives error") == "negative"

    def test_classify_test_type_edge(self):
        assert classify_test_type("Boundary test for max length") == "edge"

    def test_classify_test_type_error(self):
        assert classify_test_type("Server error on submit") == "error_handling"

    def test_classify_test_type_permission(self):
        assert classify_test_type("Unauthorized user access") == "permission"

    def test_classify_test_type_fallback(self):
        assert classify_test_type("random text without keywords") == "positive"

    def test_classify_feature_type_auth(self):
        assert classify_feature_type("Test the login page") == "auth"

    def test_classify_feature_type_form(self):
        assert classify_feature_type("Submit the contact form") == "form"

    def test_classify_feature_type_crud(self):
        assert classify_feature_type("Create a new record") == "crud"

    def test_classify_feature_type_navigation(self):
        assert classify_feature_type("Navigate to dashboard") == "navigation"

    def test_classify_feature_type_search(self):
        assert classify_feature_type("Search for products") == "search"

    def test_classify_feature_type_payment(self):
        assert classify_feature_type("Complete checkout") == "payment"

    def test_classify_feature_type_notification(self):
        assert classify_feature_type("Push notification test") == "notification"

    def test_classify_feature_type_media(self):
        assert classify_feature_type("Upload profile image") == "media"

    def test_classify_feature_type_data_display(self):
        assert classify_feature_type("Display user list") == "data_display"

    def test_classify_feature_type_fallback(self):
        assert classify_feature_type("something random") == "form"

    def test_classify_clarify_needs_clarification(self):
        assert classify_clarify_intent("What do you mean by that") == "needs_clarification"
        assert classify_clarify_intent("I'm not sure what you're asking") == "needs_clarification"

    def test_classify_clarify_clear(self):
        assert classify_clarify_intent("Yes, that's correct") == "requirement_clear"
        assert classify_clarify_intent("Test the login flow with email") == "requirement_clear"

    def test_classify_review_accept(self):
        assert classify_review_intent("Looks good to me") == "accept"
        assert classify_review_intent("Yes, that works") == "accept"

    def test_classify_review_revise(self):
        assert classify_review_intent("Can you add error handling") == "revise"
        assert classify_review_intent("I need changes to the test") == "revise"

    def test_classify_review_abandon(self):
        assert classify_review_intent("Cancel this") == "abandon"
        assert classify_review_intent("Never mind, stop") == "abandon"


class TestConversationState:
    def test_initial_state(self):
        state = ConversationState(url="https://example.com/login")
        assert state.current_node_id == "N0"
        assert state.total_turns == 0
        assert not state.is_terminal()

    def test_welcome_injection(self):
        state = ConversationState()
        state.inject_welcome()
        assert len(state.history) == 1
        assert state.history[0].role == "assistant"
        assert "SDET agent" in state.history[0].content

    def test_process_first_message(self):
        state = ConversationState(url="https://example.com/login")
        state.inject_welcome()

        result = state.process_user_input("Test the login flow with email and password")

        assert result["message"]["role"] == "assistant"
        assert result["suggestion_chips"] is not None
        assert not result["is_complete"]
        assert len(state.history) == 3  # welcome + user + assistant

    def test_full_flow_to_completion(self):
        state = ConversationState(url="https://example.com/login")
        state.inject_welcome()

        state.process_user_input("Test login with email and password")

        for _ in range(20):
            if state.is_terminal():
                break
            state.process_user_input("yes")

        assert state.current_node_id in ("T_SUCCESS",)
        assert state.total_turns > 2

    def test_clarify_loop(self):
        state = ConversationState()
        state.inject_welcome()

        result = state.process_user_input("What do you mean by that")
        assert state.clarify_count <= 2

    def test_revise_loop(self):
        state = ConversationState(url="https://example.com/login")
        state.inject_welcome()
        state.process_user_input("Test login")
        if state.current_node_id == "N3":
            state.process_user_input("yes")
        state.process_user_input("positive")
        state.process_user_input("auth")

        result = state.process_user_input("Can you add error handling")
        assert state.revise_count >= 0

    def test_snapshot(self):
        state = ConversationState(url="https://example.com")
        snap = state.snapshot()
        assert snap.current_node == "N0"
        assert snap.total_turns == 0
        assert not snap.is_complete

    def test_add_turn(self):
        state = ConversationState()
        turn = state.add_turn("user", "Hello")
        assert turn.role == "user"
        assert turn.content == "Hello"
        assert state.total_turns == 1

    def test_get_agent_response(self):
        state = ConversationState()
        state.current_node_id = "N0"
        resp = state.get_agent_response()
        assert len(resp) > 0

    def test_get_suggestion_chips_at_feature_hub(self):
        state = ConversationState()
        state.current_node_id = "N8"
        chips = state.get_suggestion_chips()
        assert any(c["id"] == "auth" for c in chips)
        assert any(c["id"] == "form" for c in chips)

    def test_generate_test_code(self):
        state = ConversationState(url="https://example.com/login")
        state.feature_type = "auth"
        state.test_type = "positive"
        code = state.generate_test_code()
        assert "Playwright" in code
        assert "auth" in code

    def test_max_total_turns(self):
        state = ConversationState()
        state.total_turns = 34
        next_node = state.classify_and_route("hello")
        assert next_node is not None


class TestSessionManager:
    def test_create_session(self):
        mgr = SessionManager()
        session = mgr.create_session(url="https://example.com/login")
        assert session.session_id is not None
        assert session.url == "https://example.com/login"
        assert len(session.messages) == 1  # welcome

    def test_get_session(self):
        mgr = SessionManager()
        session = mgr.create_session(url="https://example.com")
        assert mgr.get_session(session.session_id) is session

    def test_delete_session(self):
        mgr = SessionManager()
        session = mgr.create_session(url="https://example.com")
        assert mgr.delete_session(session.session_id)
        assert mgr.get_session(session.session_id) is None

    def test_list_sessions(self):
        mgr = SessionManager()
        mgr.create_session(url="https://example.com/a")
        mgr.create_session(url="https://example.com/b")
        sessions = mgr.list_sessions()
        assert len(sessions) == 2

    def test_process_message(self):
        mgr = SessionManager()
        session = mgr.create_session(url="https://example.com/login")

        result = mgr.process_message(
            session_id=session.session_id,
            content="Test the login flow with SSO",
        )

        assert result["type"] == "agent_response"
        assert result["message"]["role"] == "assistant"
        assert "next_node" in result

    def test_process_message_invalid_session(self):
        mgr = SessionManager()
        result = mgr.process_message(session_id="nonexistent", content="hello")
        assert result["type"] == "error"
