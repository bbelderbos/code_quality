import json
import sys
from pathlib import Path

import pytest

from pybites_quality import core
from pybites_quality.core import (
    FileMetrics,
    FunctionMetrics,
    count_typed_functions,
    summarize,
    walk_python_files,
)


def test_count_typed_functions_mixed():
    code = """
def f(x, y: int) -> None:
    return x + y

async def g(a, b):
    return a + b
"""
    total, typed = count_typed_functions(code)
    assert total == 2
    assert typed == 1


def test_count_typed_functions_syntax_error_returns_zero():
    code = "def broken(:\n    pass"
    assert count_typed_functions(code) == (0, 0)


def test_walk_python_files_ignores_virtualenv_and_caches(tmp_path: Path):
    # layout:
    # root/
    #   app.py
    #   not_py.txt
    #   .venv/ignored.py
    #   pkg/mod.py
    #   pkg/__pycache__/ignored2.py
    root = tmp_path
    (root / "app.py").write_text("print('hi')\n")
    (root / "not_py.txt").write_text("ignore me\n")

    venv_dir = root / ".venv"
    venv_dir.mkdir()
    (venv_dir / "ignored.py").write_text("print('ignore')\n")

    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("print('pkg')\n")
    cache = pkg / "__pycache__"
    cache.mkdir()
    (cache / "ignored2.py").write_text("print('ignore2')\n")

    paths = walk_python_files(root)
    rel = {p.relative_to(root).as_posix() for p in paths}
    assert "app.py" in rel
    assert "pkg/mod.py" in rel
    assert ".venv/ignored.py" not in rel
    assert "pkg/__pycache__/ignored2.py" not in rel
    assert "not_py.txt" not in rel


def _make_fm(
    *,
    path: str,
    sloc: int = 10,
    mi: float = 70.0,
    mi_rank: str = "B",
    complexity_grades: dict[str, int] | None = None,
    total_functions: int = 2,
    typed_functions: int = 1,
    cognitive_complexity: int = 5,
) -> FileMetrics:
    return FileMetrics(
        path=path,
        sloc=sloc,
        lloc=sloc - 2,
        comments=1,
        complexity_grades=complexity_grades or {"A": 1},
        worst_cc=3,
        worst_cc_rank="A",
        mi=mi,
        mi_rank=mi_rank,
        total_functions=total_functions,
        typed_functions=typed_functions,
        cognitive_complexity=cognitive_complexity,
        max_function_cognitive_complexity=cognitive_complexity + 1,
    )


def test_summarize_excludes_test_files_from_low_mi(tmp_path: Path):
    root = tmp_path

    app_file = _make_fm(path="app/module.py", mi=35.0)  # low MI (< 40.0)
    test_file = _make_fm(path="app/tests/test_module.py", mi=30.0)

    summary = summarize([app_file, test_file], root)

    # low_mi_files only counts non-test files
    assert summary.low_mi_files == 1
    # avg_mi still includes both files (uses original list)
    assert summary.avg_mi == pytest.approx((35.0 + 30.0) / 2)

    # typing + cx metrics only use non-test files (after the reassign)
    assert summary.total_functions == app_file.total_functions
    assert summary.typed_functions == app_file.typed_functions
    assert summary.typing_coverage == pytest.approx(
        app_file.typed_functions / app_file.total_functions * 100
    )

    assert summary.avg_cognitive_complexity == pytest.approx(
        app_file.cognitive_complexity
    )
    assert summary.max_cognitive_complexity == app_file.cognitive_complexity


def test_print_hotspots_orders_and_labels(capsys: pytest.CaptureFixture):
    files = [
        _make_fm(path="proj/a.py", mi=35.0),  # WATCH (< 40)
        _make_fm(path="proj/b.py", mi=55.0),  # OK (40-70)
        _make_fm(path="proj/tests/test_c.py", mi=30.0),  # excluded for MI listing
        _make_fm(path="proj/d.py", mi=85.0),  # GOOD (>= 70)
    ]
    fns = [
        FunctionMetrics(
            file="proj/a.py",
            name="foo",
            lineno=10,
            cognitive_complexity=20,
        ),
        FunctionMetrics(
            file="proj/b.py",
            name="bar",
            lineno=5,
            cognitive_complexity=10,
        ),
    ]

    core.print_hotspots(
        files,
        fns,
        mi_low_threshold=core.MI_LOW,
        mi_target=core.MI_HIGH,
        cx_function_target=core.COGNITIVE_COMPLEXITY_TARGET,
        top_n=2,
        root=Path("proj"),
    )

    out = capsys.readouterr().out

    assert "Top 2 lowest MI files" in out
    assert "a.py" in out
    assert "[WATCH]" in out

    assert "test_c.py" not in out

    assert "Top 2 most complex functions" in out
    assert "foo" in out
    assert "bar" in out


def _fake_metrics_for_main(path: Path) -> tuple[FileMetrics, list[FunctionMetrics]]:
    fm = _make_fm(
        path=str(path),
        sloc=20,
        mi=70.0,
        total_functions=2,
        typed_functions=2,
        cognitive_complexity=8,
    )
    fns = [
        FunctionMetrics(file=str(path), name="foo", lineno=1, cognitive_complexity=12)
    ]
    return fm, fns


def test_main_passes_when_thresholds_met(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    root = tmp_path

    # monkeypatch file discovery + analysis
    monkeypatch.setattr(core, "walk_python_files", lambda r: [root / "dummy.py"])
    monkeypatch.setattr(core, "analyze_file", lambda p: _fake_metrics_for_main(p))

    # config should return defaults if not overridden on CLI
    def fake_config(name, default=None, cast=float):
        return default

    monkeypatch.setattr(core, "config", fake_config)

    argv = ["pybites-quality", str(root)]
    monkeypatch.setattr(sys, "argv", argv)

    core.main()
    out = capsys.readouterr().out
    assert "Pybites maintainability snapshot for" in out
    assert "[FAIL]" not in out


def test_main_fails_when_env_thresholds_higher_than_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    root = tmp_path

    monkeypatch.setattr(core, "walk_python_files", lambda r: [root / "dummy.py"])
    monkeypatch.setattr(core, "analyze_file", lambda p: _fake_metrics_for_main(p))

    # Make env thresholds stricter than our fake metrics
    def fake_config(name, default=None, cast=float):
        if name == "PYBITES_QUALITY_FAIL_MI_BELOW":
            return 75.0  # avg MI is 70.0
        if name == "PYBITES_QUALITY_FAIL_TYPING_BELOW":
            return 110.0  # higher than 100%
        return default

    monkeypatch.setattr(core, "config", fake_config)

    argv = ["pybites-quality", str(root)]
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        core.main()

    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "[FAIL] Average MI" in out
    assert "Typing coverage" in out


def test_main_cli_threshold_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    root = tmp_path

    monkeypatch.setattr(core, "walk_python_files", lambda r: [root / "dummy.py"])
    monkeypatch.setattr(core, "analyze_file", lambda p: _fake_metrics_for_main(p))

    # config would make it fail if used, so this verifies CLI wins
    def fake_config(name, default=None, cast=float):
        if name == "PYBITES_QUALITY_FAIL_MI_BELOW":
            return 10.0
        if name == "PYBITES_QUALITY_FAIL_TYPING_BELOW":
            return 10.0
        return default

    monkeypatch.setattr(core, "config", fake_config)

    # thresholds via CLI are low, so it should pass
    argv = [
        "pybites-quality",
        str(root),
        "--fail-mi-below",
        "50",
        "--fail-typing-below",
        "50",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    core.main()
    out = capsys.readouterr().out
    assert "[FAIL]" not in out


def test_main_json_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    root = tmp_path

    monkeypatch.setattr(core, "walk_python_files", lambda r: [root / "dummy.py"])
    monkeypatch.setattr(core, "analyze_file", lambda p: _fake_metrics_for_main(p))
    monkeypatch.setattr(
        core,
        "config",
        lambda name, default=None, cast=float: default,
    )

    argv = ["pybites-quality", str(root), "--json"]
    monkeypatch.setattr(sys, "argv", argv)

    core.main()
    out = capsys.readouterr().out
    data = json.loads(out)

    assert data["root"] == str(root.resolve())
    assert data["files_scanned"] == 1
    assert data["total_sloc"] == 20
    assert data["typing_coverage"] == pytest.approx(100.0)


def test_main_nonexistent_root_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    argv = ["pybites-quality", str(tmp_path / "does_not_exist")]
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        core.main()

    # message is passed to SystemExit
    assert "Path not found" in str(exc.value)


def test_count_typed_functions_vararg_and_kwarg():
    code = """
def f(*args: int, **kwargs: str):
    return 42
"""
    total, typed = count_typed_functions(code)
    assert total == 1
    assert typed == 1


def test_analyze_file_smoke(tmp_path: Path):
    path = tmp_path / "mod.py"
    path.write_text(
        "def foo(x: int) -> int:\n" "    y = x + 1\n" "    return y\n",
        encoding="utf-8",
    )

    result = core.analyze_file(path)
    assert result is not None

    fm, fns = result
    assert fm.path.endswith("mod.py")
    assert fm.sloc > 0
    assert fm.total_functions >= 1
    assert fm.typed_functions >= 1
    assert fm.cognitive_complexity >= 0
    assert any(fn.name == "foo" for fn in fns)


def test_print_hotspots_relative_errors_and_good_label(tmp_path: Path, capsys):
    root = tmp_path / "root"
    root.mkdir()

    outside = tmp_path / "other" / "a.py"
    outside.parent.mkdir()
    fm = _make_fm(path=str(outside), mi=85.0)  # >= MI_HIGH -> GOOD label

    fns = [
        FunctionMetrics(
            file=str(outside),
            name="foo",
            lineno=10,
            cognitive_complexity=30,
        )
    ]

    core.print_hotspots(
        [fm],
        fns,
        mi_low_threshold=core.MI_LOW,
        mi_target=core.MI_HIGH,
        top_n=1,
        root=root,
    )

    out = capsys.readouterr().out
    # rel() should fall back to the full path when relative_to() fails
    assert str(outside) in out
    assert "[GOOD]" in out


def test_main_skips_files_where_analyze_file_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    root = tmp_path

    f1 = root / "a.py"
    f1.write_text("x = 1\n")
    f2 = root / "b.py"
    f2.write_text("x = 2\n")

    def fake_walk(r):
        return [f1, f2]

    def fake_analyze(path):
        if path == f1:
            return None
        return _fake_metrics_for_main(path)

    monkeypatch.setattr(core, "walk_python_files", fake_walk)
    monkeypatch.setattr(core, "analyze_file", fake_analyze)
    monkeypatch.setattr(core, "config", lambda name, default=None, cast=float: default)

    argv = ["pybites-quality", str(root)]
    monkeypatch.setattr(sys, "argv", argv)

    core.main()
    out = capsys.readouterr().out

    # Only one file should be counted
    assert "Files scanned              : 1" in out
