from textual.widgets import RichLog, Static
from textual.containers import Vertical


class ImpactPanel(Static):
    def compose(self):
        with Vertical():
            yield RichLog(id="impact-log", highlight=True, wrap=True)

    def on_mount(self):
        self.query_one("#impact-log", RichLog).write("[dim]TIA results will appear here after analysis.[/dim]")

    def show_impact(self, changed_files: list[str], impacted_tests: list[dict], coverage_gaps: list[str]):
        log = self.query_one("#impact-log", RichLog)
        log.clear()
        log.write("[bold]Test Impact Analysis[/bold]")
        log.write("─" * 40)
        log.write(f"\n[bold]Changed Files:[/bold] {len(changed_files)}")
        for f in changed_files[:5]:
            log.write(f"  {f}")
        if len(changed_files) > 5:
            log.write(f"  ... and {len(changed_files) - 5} more")
        log.write(f"\n[bold]Impacted Tests:[/bold] {len(impacted_tests)}")
        for t in impacted_tests[:5]:
            log.write(f"  {t.get('name', '?')}")
        if len(impacted_tests) > 5:
            log.write(f"  ... and {len(impacted_tests) - 5} more")
        if coverage_gaps:
            log.write(f"\n[bold yellow]Coverage Gaps:[/bold] {len(coverage_gaps)}")
            for g in coverage_gaps[:3]:
                log.write(f"  [yellow]{g}[/yellow]")

    def clear(self):
        self.query_one("#impact-log", RichLog).clear()
