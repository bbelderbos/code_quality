from pathlib import Path

import pytest

from pybites_quality import tui
from pybites_quality.core import FileMetrics, FunctionMetrics


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


def _fake_metrics(path: Path) -> tuple[FileMetrics, list[FunctionMetrics]]:
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


class TestFindRepos:
    def test_find_repos_with_pyproject_toml(self, tmp_path: Path):
        # Create a repo with pyproject.toml
        repo = tmp_path / "my_repo"
        repo.mkdir()
        (repo / "pyproject.toml").touch()

        repos = list(tui.find_repos(tmp_path))
        assert len(repos) == 1
        assert repos[0] == repo

    def test_find_repos_with_setup_py(self, tmp_path: Path):
        repo = tmp_path / "legacy_repo"
        repo.mkdir()
        (repo / "setup.py").touch()

        repos = list(tui.find_repos(tmp_path))
        assert len(repos) == 1
        assert repos[0] == repo

    def test_find_repos_with_git(self, tmp_path: Path):
        repo = tmp_path / "git_repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        repos = list(tui.find_repos(tmp_path))
        assert len(repos) == 1
        assert repos[0] == repo

    def test_find_repos_with_setup_cfg(self, tmp_path: Path):
        repo = tmp_path / "cfg_repo"
        repo.mkdir()
        (repo / "setup.cfg").touch()

        repos = list(tui.find_repos(tmp_path))
        assert len(repos) == 1
        assert repos[0] == repo

    def test_find_repos_multiple_repos(self, tmp_path: Path):
        # Create multiple repos
        repo1 = tmp_path / "alpha_repo"
        repo1.mkdir()
        (repo1 / "pyproject.toml").touch()

        repo2 = tmp_path / "beta_repo"
        repo2.mkdir()
        (repo2 / "setup.py").touch()

        repos = list(tui.find_repos(tmp_path))
        assert len(repos) == 2
        # Should be sorted alphabetically
        assert repos[0] == repo1
        assert repos[1] == repo2

    def test_find_repos_ignores_files(self, tmp_path: Path):
        # Create a file, not a directory
        (tmp_path / "file.txt").touch()
        # Create a valid repo
        repo = tmp_path / "valid_repo"
        repo.mkdir()
        (repo / "pyproject.toml").touch()

        repos = list(tui.find_repos(tmp_path))
        assert len(repos) == 1
        assert repos[0] == repo

    def test_find_repos_ignores_dirs_without_markers(self, tmp_path: Path):
        # Create a directory without any markers
        non_repo = tmp_path / "just_a_dir"
        non_repo.mkdir()
        (non_repo / "random_file.py").touch()

        repos = list(tui.find_repos(tmp_path))
        assert len(repos) == 0

    def test_find_repos_nonexistent_base_dir(self, tmp_path: Path):
        fake_dir = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError) as exc:
            list(tui.find_repos(fake_dir))
        assert "does not exist or is not a directory" in str(exc.value)

    def test_find_repos_base_is_file(self, tmp_path: Path):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.touch()

        with pytest.raises(FileNotFoundError) as exc:
            list(tui.find_repos(file_path))
        assert "does not exist or is not a directory" in str(exc.value)


class TestScanProject:
    def test_scan_project_basic(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Create a simple project structure
        monkeypatch.setattr(tui, "walk_python_files", lambda r: [tmp_path / "app.py"])
        monkeypatch.setattr(tui, "analyze_file", lambda p: _fake_metrics(p))

        summary, worst_files, worst_fns, skipped = tui.scan_project(tmp_path)

        assert summary.files_scanned == 1
        assert summary.total_sloc == 20
        assert len(worst_files) == 1
        assert len(worst_fns) == 1
        assert len(skipped) == 0

    def test_scan_project_excludes_test_files_from_worst(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Simulate files including a test file
        app_path = tmp_path / "app.py"
        test_path = tmp_path / "tests" / "test_app.py"

        def fake_walk(r):
            return [app_path, test_path]

        def fake_analyze(p):
            if "tests" in str(p):
                fm = _make_fm(path=str(p), mi=30.0)  # Low MI
            else:
                fm = _make_fm(path=str(p), mi=70.0)
            fns = [
                FunctionMetrics(
                    file=str(p), name="test_func", lineno=1, cognitive_complexity=5
                )
            ]
            return fm, fns

        monkeypatch.setattr(tui, "walk_python_files", fake_walk)
        monkeypatch.setattr(tui, "analyze_file", fake_analyze)

        summary, worst_files, worst_fns, skipped = tui.scan_project(tmp_path)

        # Test files should be excluded from worst_files
        assert len(worst_files) == 1
        assert "tests" not in worst_files[0].path

    def test_scan_project_handles_syntax_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        bad_file = tmp_path / "bad.py"
        good_file = tmp_path / "good.py"

        def fake_walk(r):
            return [bad_file, good_file]

        def fake_analyze(p):
            if p == bad_file:
                raise SyntaxError("Fake syntax error")
            return _fake_metrics(p)

        monkeypatch.setattr(tui, "walk_python_files", fake_walk)
        monkeypatch.setattr(tui, "analyze_file", fake_analyze)

        summary, worst_files, worst_fns, skipped = tui.scan_project(tmp_path)

        assert len(skipped) == 1
        assert skipped[0] == bad_file
        assert summary.files_scanned == 1

    def test_scan_project_handles_none_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        unreadable = tmp_path / "unreadable.py"
        readable = tmp_path / "readable.py"

        def fake_walk(r):
            return [unreadable, readable]

        def fake_analyze(p):
            if p == unreadable:
                return None
            return _fake_metrics(p)

        monkeypatch.setattr(tui, "walk_python_files", fake_walk)
        monkeypatch.setattr(tui, "analyze_file", fake_analyze)

        summary, worst_files, worst_fns, skipped = tui.scan_project(tmp_path)

        # File returning None is not in skipped (only SyntaxError goes there)
        assert len(skipped) == 0
        assert summary.files_scanned == 1

    def test_scan_project_limits_worst_to_10(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Create 15 files
        files = [tmp_path / f"file_{i}.py" for i in range(15)]

        def fake_walk(r):
            return files

        def fake_analyze(p):
            # Give each file a different MI score
            idx = int(p.stem.split("_")[1])
            fm = _make_fm(path=str(p), mi=50.0 + idx)
            fns = [
                FunctionMetrics(
                    file=str(p), name=f"func_{idx}", lineno=1, cognitive_complexity=idx
                )
            ]
            return fm, fns

        monkeypatch.setattr(tui, "walk_python_files", fake_walk)
        monkeypatch.setattr(tui, "analyze_file", fake_analyze)

        summary, worst_files, worst_fns, skipped = tui.scan_project(tmp_path)

        # Should be limited to 10 worst
        assert len(worst_files) <= 10
        assert len(worst_fns) <= 10

    def test_scan_project_sorts_files_by_mi_ascending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        files = [tmp_path / f"file_{i}.py" for i in range(5)]

        def fake_walk(r):
            return files

        def fake_analyze(p):
            idx = int(p.stem.split("_")[1])
            # Higher index = higher MI (better quality)
            fm = _make_fm(path=str(p), mi=50.0 + idx * 10)
            return fm, []

        monkeypatch.setattr(tui, "walk_python_files", fake_walk)
        monkeypatch.setattr(tui, "analyze_file", fake_analyze)

        summary, worst_files, worst_fns, skipped = tui.scan_project(tmp_path)

        # worst_files should be sorted by MI ascending (worst first)
        mi_values = [f.mi for f in worst_files]
        assert mi_values == sorted(mi_values)

    def test_scan_project_sorts_functions_by_complexity_descending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        files = [tmp_path / f"file_{i}.py" for i in range(3)]

        def fake_walk(r):
            return files

        def fake_analyze(p):
            idx = int(p.stem.split("_")[1])
            fm = _make_fm(path=str(p), mi=70.0)
            fns = [
                FunctionMetrics(
                    file=str(p),
                    name=f"func_{idx}",
                    lineno=1,
                    cognitive_complexity=10 + idx * 5,
                )
            ]
            return fm, fns

        monkeypatch.setattr(tui, "walk_python_files", fake_walk)
        monkeypatch.setattr(tui, "analyze_file", fake_analyze)

        summary, worst_files, worst_fns, skipped = tui.scan_project(tmp_path)

        # worst_fns should be sorted by complexity descending (worst first)
        complexities = [fn.cognitive_complexity for fn in worst_fns]
        assert complexities == sorted(complexities, reverse=True)
