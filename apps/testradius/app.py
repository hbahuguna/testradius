import asyncio
import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.layouts.grid import GridLayout
from textual.binding import Binding
from textual.widgets import Header, Footer, Input

from .panels.chat import ChatPanel
from .panels.elements import ElementsPanel
from .panels.test_code import TestCodePanel
from .panels.impact import ImpactPanel
from .bridge.opencode import OpenCodeBridge
from .server.http_server import LocalHTTPServer


CSS = """
#main-grid {
    grid-size: 3 2;
    grid-rows: auto 1fr auto;
    grid-columns: 1fr 2fr;
}

#chat-panel {
    row-span: 2;
    column-span: 1;
    border: solid $primary;
}

#right-column {
    row-span: 2;
    column-span: 2;
    grid-size: 1 3;
    grid-rows: 1fr 2fr 1fr;
}

#elements-panel {
    border: solid $secondary;
}

#test-code-panel {
    border: solid $accent;
}

#impact-panel {
    border: solid $warning;
}

#input-bar {
    column-span: 3;
    dock: bottom;
}
"""


class TestRadius(App):
    TITLE = "testradius"
    SUB_TITLE = "AI-Powered SDET Assistant"

    CSS = CSS

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear_chat", "Clear Chat"),
    ]

    def __init__(self, repo_path: str | None = None):
        super().__init__()
        self._repo_path = repo_path or Path.cwd()
        self._bridge = OpenCodeBridge(repo_path=self._repo_path)
        self._http_server: LocalHTTPServer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with GridLayout(id="main-grid"):
            yield ChatPanel(id="chat-panel")
            with GridLayout(id="right-column"):
                yield ElementsPanel(id="elements-panel")
                yield TestCodePanel(id="test-code-panel")
                yield ImpactPanel(id="impact-panel")
        yield Input(id="input-bar", placeholder="Describe the test you want to generate...")
        yield Footer()

    def on_mount(self):
        self._start_http_server()

    def _start_http_server(self):
        server = LocalHTTPServer(repo_path=self._repo_path)
        thread = threading.Thread(target=server.start, daemon=True)
        thread.start()
        self._http_server = server
        self.call_from_thread(
            self.query_one("#chat-panel", ChatPanel).append_agent_message,
            f"HTTP server running on {server.base_url}"
        )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            return

        input_bar = self.query_one("#input-bar", Input)
        input_bar.disabled = True

        chat = self.query_one("#chat-panel", ChatPanel)
        test_code = self.query_one("#test-code-panel", TestCodePanel)
        impact = self.query_one("#impact-panel", ImpactPanel)
        elements = self.query_one("#elements-panel", ElementsPanel)

        chat.append_user_message(event.value)
        chat.append_agent_message("Processing...")

        code_buffer = ""
        try:
            async for evt in self._bridge.run(event.value):
                evt_type = evt.get("type", "")
                evt_event = evt.get("event", "")
                content = evt.get("content", "")
                code = evt.get("code", "")

                if evt_type == "thinking":
                    chat.append_thinking(content.strip())
                elif evt_type in ("text", "message") or evt_event == "text":
                    chat.append_agent_message(content.strip())
                elif evt_type == "code" or evt_event == "code":
                    if code:
                        test_code.show_code(code)
                        code_buffer = code
                elif evt_type == "tool_call":
                    tool_name = evt.get("tool", "")
                    chat.append_agent_message(f"[dim]Calling tool: {tool_name}[/dim]")
                elif evt_type == "error":
                    chat.append_agent_message(f"[red]Error: {content}[/red]")
        except Exception as e:
            chat.append_agent_message(f"[red]Bridge error: {e}[/red]")

        input_bar.disabled = False
        input_bar.clear()

    def action_clear_chat(self) -> None:
        self.query_one("#chat-panel", ChatPanel).clear()

    def on_unmount(self):
        if self._http_server:
            self._http_server.stop()
