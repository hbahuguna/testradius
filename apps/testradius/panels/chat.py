from textual.widgets import RichLog
from textual.containers import Vertical
from textual.widget import Widget


class ChatPanel(Widget):
    def compose(self):
        with Vertical():
            yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)

    def on_mount(self):
        log = self.query_one("#chat-log", RichLog)
        log.write("[bold blue]testradius[/] ready. Describe the test you want to generate.")
        log.write("I'll analyze the app, generate Playwright code, and suggest which tests to run.")
        log.write("─" * 50)

    def append_user_message(self, text: str):
        self.query_one("#chat-log", RichLog).write(f"\n[bold yellow]You:[/] {text}")

    def append_agent_message(self, text: str):
        self.query_one("#chat-log", RichLog).write(f"\n[bold green]Agent:[/] {text}")

    def append_thinking(self, text: str):
        if text:
            self.query_one("#chat-log", RichLog).write(f"[dim italic]{text}[/dim]")

    def clear(self):
        self.query_one("#chat-log", RichLog).clear()
        self.on_mount()
