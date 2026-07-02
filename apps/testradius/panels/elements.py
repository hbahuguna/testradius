from textual.widgets import RichLog, Static
from textual.containers import Vertical


class ElementsPanel(Static):
    def compose(self):
        with Vertical():
            yield RichLog(id="elements-log", highlight=True, wrap=True)

    def on_mount(self):
        self.query_one("#elements-log", RichLog).write("[dim]No page loaded yet.[/dim]")

    def show_elements(self, elements: list[dict]):
        log = self.query_one("#elements-log", RichLog)
        log.clear()
        log.write(f"[bold]Interactive Elements ({len(elements)})[/bold]")
        log.write("─" * 40)
        for el in elements:
            tag = el.get("tag", "?")
            text = el.get("text", "")[:60]
            selector = el.get("selector", "")
            log.write(f"[bold]{tag}[/bold] {text}")
            log.write(f"  [dim]{selector}[/dim]")

    def show_error(self, message: str):
        log = self.query_one("#elements-log", RichLog)
        log.clear()
        log.write(f"[red]Error:[/red] {message}")
