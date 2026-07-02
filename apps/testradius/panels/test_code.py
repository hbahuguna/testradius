from textual.widgets import RichLog, Static
from textual.containers import Vertical


class TestCodePanel(Static):
    def compose(self):
        with Vertical():
            yield RichLog(id="code-log", highlight=True, wrap=True)

    def on_mount(self):
        self.query_one("#code-log", RichLog).write("[dim]Generated test code will appear here.[/dim]")

    def show_code(self, code: str):
        log = self.query_one("#code-log", RichLog)
        log.clear()
        log.write(code)

    def append_code(self, code: str):
        self.query_one("#code-log", RichLog).write(code)

    def clear(self):
        self.query_one("#code-log", RichLog).clear()
