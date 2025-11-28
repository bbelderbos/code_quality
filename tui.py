from pathlib import Path
import subprocess
from typing import Iterable

from decouple import config
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.events import Key
from textual.widgets import (
    Header,
    Footer,
    Input,
    Button,
    DataTable,
    Static,
    OptionList,
)
from textual.screen import Screen


from quality import (
    analyze_file,
    summarize,
    walk_python_files,
    FileMetrics,
    FunctionMetrics,
    MI_LOW,
    MI_HIGH,
    COGNITIVE_COMPLEXITY_THRESHOLD,
)

DEFAULT_CODE_REPO = config("DEFAULT_CODE_REPO", default="~/code")
DEFAULT_EDITOR = config("DEFAULT_EDITOR", default="vim")


def scan_project(root: Path):
    """Reuse your existing logic to compute summary + hotspots."""
    py_files = walk_python_files(root)
    file_metrics: list[FileMetrics] = []
    fn_metrics: list[FunctionMetrics] = []

    skipped = 0
    for path in py_files:
        try:
            result = analyze_file(path)
        except SyntaxError:
            # Skip files radon can't parse (or optionally log them somewhere)
            skipped += 1
            continue

        if result is None:
            continue

        fm, fns = result
        file_metrics.append(fm)
        fn_metrics.extend(fns)

    summary = summarize(file_metrics, root)

    non_test_files = [f for f in file_metrics if "/tests/" not in f.path]
    worst_files = sorted(non_test_files, key=lambda f: f.mi)[:10]
    worst_fns = sorted(
        fn_metrics, key=lambda fn: fn.cognitive_complexity, reverse=True
    )[:10]

    return summary, worst_files, worst_fns, skipped


def find_repos(base_dir: Path) -> Iterable[Path]:
    """Yield directories under base_dir that look like Python projects."""
    markers = {"pyproject.toml", "setup.cfg", "setup.py", ".git"}
    if not base_dir.is_dir():
        raise FileNotFoundError(f"Base directory '{base_dir}' does not exist or is not a directory.")
    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir():
            continue
        if any((entry / m).exists() for m in markers):
            yield entry


class QualityApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #top-bar {
        height: 3;
    }

    #summary {
        height: 7;
        border: round $accent;
        padding: 1;
    }

    #tables {
        height: 1fr;
    }

    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "rescan", "Rescan current path"),
        ("p", "pick_repo", "Pick repo under ~/code"),  # NEW
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="top-bar"):
            self.path_input = Input(
                placeholder="Project path (default: .)", value=".", id="path-input"
            )
            yield self.path_input
            yield Button("Scan", id="scan-btn")

        self.summary_box = Static(id="summary")
        yield self.summary_box

        with Horizontal(id="tables"):
            self.files_table = DataTable(id="files-table")
            self.funcs_table = DataTable(id="funcs-table")
            yield self.files_table
            yield self.funcs_table

        yield Footer()

    def on_mount(self) -> None:
        self._setup_tables()
        self.current_root = Path(".")
        self.current_functions: list[FunctionMetrics] = []
        self._run_scan(Path("."))

    def _setup_tables(self) -> None:
        self.files_table.clear()
        self.files_table.add_columns("MI", "Label", "Path")

        self.funcs_table.clear()
        self.funcs_table.add_columns("Cx", "Flag", "File:Line", "Function")

    def _run_scan(self, root: Path) -> None:
        self.current_root = root
        self.summary_box.update(f"Scanning {root} ...")

        summary, worst_files, worst_fns, skipped = scan_project(root)
        self.current_functions = worst_fns

        # summary text
        summary_text = (
            f"[b]PyBites maintainability snapshot[/b]\n"
            f"Root: {summary.root}\n"
            f"Files scanned          : {summary.files_scanned}\n"
            f"Files skipped (syntax) : {skipped}\n"
            f"Total SLOC             : {summary.total_sloc}\n"
            f"Avg SLOC per file      : {summary.avg_sloc_per_file:.1f}\n"
            f"Avg MI                 : {summary.avg_mi:.1f} "
            f"(<{MI_LOW:.0f}=watch, {MI_LOW:.0f}–{MI_HIGH:.0f}=moderate, >{MI_HIGH:.0f}=high)\n"
            f"Low MI files (<{MI_LOW:.0f}) : {summary.low_mi_files}\n"
            f"Typing coverage        : {summary.typing_coverage:.1f}% "
            f"({summary.typed_functions}/{summary.total_functions} funcs)\n"
            f"Avg cognitive compl.   : {summary.avg_cognitive_complexity:.1f}\n"
            f"Max cognitive compl.   : {summary.max_cognitive_complexity}\n"
        )
        self.summary_box.update(summary_text)

        # files table
        self.files_table.clear()

        for f in worst_files:
            if f.mi < MI_LOW:
                label = "[bold red]WATCH[/]"
                mi_text = f"[bold red]{f.mi:5.1f}[/]"
            elif f.mi >= MI_HIGH:
                label = "[green]GOOD[/]"
                mi_text = f"[green]{f.mi:5.1f}[/]"
            else:
                label = "[yellow]OK[/]"
                mi_text = f"[yellow]{f.mi:5.1f}[/]"

            rel_path = str(Path(f.path).relative_to(root))
            self.files_table.add_row(mi_text, label, rel_path)

        # functions table
        self.funcs_table.clear()
        for fn in worst_fns:
            if fn.cognitive_complexity > COGNITIVE_COMPLEXITY_THRESHOLD:
                flag = "[bold red]OVER[/]"
                cx_text = f"[bold red]{fn.cognitive_complexity}[/]"
            else:
                flag = "OK"
                cx_text = str(fn.cognitive_complexity)

            rel_file = str(Path(fn.file).relative_to(root))
            loc = f"{rel_file}:{fn.lineno}"
            self.funcs_table.add_row(cx_text, flag, loc, fn.name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "scan-btn":
            root = Path(self.path_input.value or ".").expanduser().resolve()
            self._run_scan(root)

    def action_rescan(self) -> None:
        root = Path(self.path_input.value or ".").expanduser().resolve()
        self._run_scan(root)

    def on_key(self, event: Key) -> None:
        if event.key == "enter" and self.focused is self.funcs_table:
            coord = self.funcs_table.cursor_coordinate
            if coord is None:
                return

            row_index, _ = coord
            if row_index >= len(self.current_functions):
                return

            fn = self.current_functions[row_index]
            file = fn.file  # absolute path from analyze_file
            line = fn.lineno

            with self.suspend():
                subprocess.run([DEFAULT_EDITOR, f"+{line}", file])

    def action_pick_repo(self) -> None:
        base = Path(DEFAULT_CODE_REPO).expanduser()
        self.push_screen(RepoPicker(base))


class RepoPicker(Screen):
    """Modal screen to pick a repo under ~/code with fuzzy search."""

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(self, base_dir: Path) -> None:
        super().__init__()
        self.base_dir = base_dir
        self._repos: list[Path] = []
        self._matched: list[Path] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter repos…", id="repo-filter")
        yield OptionList(id="repo-list")

    def on_mount(self) -> None:
        self._repos = list(find_repos(self.base_dir))
        self._refresh_list("")

        self.query_one("#repo-filter", Input).focus()

    def _refresh_list(self, query: str) -> None:
        query = query.lower()
        ol = self.query_one("#repo-list", OptionList)
        ol.clear_options()

        def score(p: Path) -> int:
            name = p.name.lower()
            if not query:
                return 0
            if name.startswith(query):
                return -2
            if query in name:
                return -1
            return 0

        matched = sorted(self._repos, key=score)
        if query:
            matched = [p for p in matched if query in p.name.lower()]

        # keep the currently visible list so we can index into it later
        self._matched = matched

        for p in matched:
            ol.add_option(p.name)  # just label, no Option / id

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "repo-filter":
            self._refresh_list(event.value)

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx is None or not (0 <= idx < len(self._matched)):
            return

        path = self._matched[idx]

        app = self.app
        if isinstance(app, QualityApp):
            app.path_input.value = str(path)
            app._run_scan(path)

        app.pop_screen()


if __name__ == "__main__":
    QualityApp().run()
