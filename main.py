"""
Quick-and-dirty local maintainability probe.

Usage:
    python quality.py /path/to/project
"""

import argparse
import ast
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import mean

from radon.raw import analyze
from radon.complexity import cc_visit, cc_rank
from radon.metrics import mi_visit, mi_rank
from complexipy import file_complexity


@dataclass
class FileMetrics:
    path: str
    sloc: int
    lloc: int
    comments: int
    complexity_grades: dict[str, int]
    worst_cc: int
    worst_cc_rank: str
    mi: float
    mi_rank: str
    total_functions: int
    typed_functions: int
    cognitive_complexity: int
    max_function_cognitive_complexity: int


@dataclass
class FunctionMetrics:
    file: str
    name: str
    lineno: int
    cognitive_complexity: int


@dataclass
class ProjectSummary:
    root: str
    files_scanned: int
    total_sloc: int
    avg_sloc_per_file: float
    avg_mi: float
    low_mi_files: int
    high_complexity_functions: int
    cc_grade_counts: dict[str, int]
    total_functions: int
    typed_functions: int
    typing_coverage: float
    avg_cognitive_complexity: float
    max_cognitive_complexity: int


def count_typed_functions(code: str) -> tuple[int, int]:
    """Return (total_functions, typed_functions) using AST."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0, 0

    total = 0
    typed = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            total += 1

            args = []
            # pos-only, regular, kw-only
            args.extend(node.args.posonlyargs)
            args.extend(node.args.args)
            args.extend(node.args.kwonlyargs)

            has_arg_anno = any(a.annotation is not None for a in args)

            vararg = node.args.vararg
            kwarg = node.args.kwarg
            if vararg is not None and vararg.annotation is not None:
                has_arg_anno = True
            if kwarg is not None and kwarg.annotation is not None:
                has_arg_anno = True

            has_return_anno = node.returns is not None

            if has_arg_anno or has_return_anno:
                typed += 1

    return total, typed


def analyze_file(path: Path) -> tuple[FileMetrics, list[FunctionMetrics]] | None:
    try:
        code = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None

    raw = analyze(code)
    cc_results = cc_visit(code)
    mi_value = mi_visit(code, multi=True)
    mi_r = mi_rank(mi_value)

    grades: dict[str, int] = {}
    worst_cc = 0
    worst_rank = "A"

    for r in cc_results:
        grade = cc_rank(r.complexity)
        grades[grade] = grades.get(grade, 0) + 1
        if r.complexity > worst_cc:
            worst_cc = r.complexity
            worst_rank = grade

    # --- complexipy: file + per-function cognitive complexity ---
    cx_result = file_complexity(str(path))
    file_cx = int(cx_result.complexity)

    fn_metrics: list[FunctionMetrics] = []
    max_func_cx = 0
    for fn in cx_result.functions:
        c = int(fn.complexity)
        max_func_cx = max(max_func_cx, c)
        fn_metrics.append(
            FunctionMetrics(
                file=str(path),
                name=fn.name,
                lineno=fn.line_start,
                cognitive_complexity=c,
            )
        )

    total_funcs, typed_funcs = count_typed_functions(code)

    file_metrics = FileMetrics(
        path=str(path),
        sloc=raw.sloc,
        lloc=raw.lloc,
        comments=raw.comments,
        complexity_grades=grades,
        worst_cc=worst_cc,
        worst_cc_rank=worst_rank,
        mi=mi_value,
        mi_rank=mi_r,
        total_functions=total_funcs,
        typed_functions=typed_funcs,
        cognitive_complexity=file_cx,
        max_function_cognitive_complexity=max_func_cx,
    )

    return file_metrics, fn_metrics


def walk_python_files(root: Path) -> list[Path]:
    ignore_dirs = {".git", ".venv", "venv", ".mypy_cache", "__pycache__"}
    paths: list[Path] = []
    for p in root.rglob("*.py"):
        if any(part in ignore_dirs for part in p.parts):
            continue
        paths.append(p)
    return paths


def summarize(files: list[FileMetrics], root: Path) -> ProjectSummary:
    total_sloc = sum(f.sloc for f in files)
    mi_values = [f.mi for f in files if f.mi > 0]

    LOW_MI_THRESHOLD = 65.0  # tweak to taste

    low_mi_files = sum(f.mi < LOW_MI_THRESHOLD for f in files)

    high_cc = 0
    grade_counts: dict[str, int] = {}
    for f in files:
        for grade, count in f.complexity_grades.items():
            grade_counts[grade] = grade_counts.get(grade, 0) + count
            if grade in ("D", "E", "F"):
                high_cc += count

    total_functions = sum(f.total_functions for f in files)
    typed_functions = sum(f.typed_functions for f in files)
    typing_coverage = (
        typed_functions / total_functions * 100 if total_functions else 0.0
    )

    cx_values = [f.cognitive_complexity for f in files]
    avg_cx = mean(cx_values) if cx_values else 0.0
    max_cx = max(cx_values) if cx_values else 0

    return ProjectSummary(
        root=str(root),
        files_scanned=len(files),
        total_sloc=total_sloc,
        avg_sloc_per_file=total_sloc / len(files) if files else 0.0,
        avg_mi=mean(mi_values) if mi_values else 0.0,
        low_mi_files=low_mi_files,
        high_complexity_functions=high_cc,
        cc_grade_counts=grade_counts,
        total_functions=total_functions,
        typed_functions=typed_functions,
        typing_coverage=typing_coverage,
        avg_cognitive_complexity=avg_cx,
        max_cognitive_complexity=max_cx,
    )


def print_hotspots(
    files: list[FileMetrics],
    functions: list[FunctionMetrics],
    mi_low_threshold: float = 65.0,
    mi_target: float = 85.0,
    cx_function_target: int = 15,
    top_n: int = 5,
) -> None:
    print(
        f"\nTop {top_n} lowest MI files "
        f"(MI < {mi_low_threshold} = difficult, >= {mi_target} = high):"
    )
    worst_files = sorted(files, key=lambda f: f.mi)[:top_n]
    for f in worst_files:
        if f.mi < mi_low_threshold:
            label = "LOW"
        elif f.mi >= mi_target:
            label = "HIGH"
        else:
            label = "MED"
        print(f"  {f.mi:5.1f} [{label}]  {f.path}")

    print(
        f"\nTop {top_n} most complex functions "
        f"(target cognitive complexity <= {cx_function_target}):"
    )
    worst_fns = sorted(functions, key=lambda fn: fn.cognitive_complexity, reverse=True)[
        :top_n
    ]
    for fn in worst_fns:
        flag = "OVER" if fn.cognitive_complexity > cx_function_target else "OK"
        print(
            f"  {fn.cognitive_complexity:3d} [{flag}]  "
            f"{fn.file}:{fn.lineno}  {fn.name}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Quick PyBites maintainability probe (static only)."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Project root to scan (default: current dir)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of human-readable text",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"Path not found: {root}")

    py_files = walk_python_files(root)
    file_metrics: list[FileMetrics] = []
    function_metrics: list[FunctionMetrics] = []

    for path in py_files:
        result = analyze_file(path)
        if result is None:
            continue
        fm, fns = result
        file_metrics.append(fm)
        function_metrics.extend(fns)

    summary = summarize(file_metrics, root)

    if args.json:
        print(json.dumps(asdict(summary), indent=2))
        return

    print(f"PyBites maintainability snapshot for: {summary.root}")
    print(f"  Files scanned              : {summary.files_scanned}")
    print(f"  Total SLOC                 : {summary.total_sloc}")
    print(f"  Avg SLOC per file          : {summary.avg_sloc_per_file:.1f}")
    print(
        f"  Avg MI (all files)         : {summary.avg_mi:.1f}  "
        "(65–85 = moderate, >85 = high)"
    )
    print(f"  Files with low MI (<65)    : {summary.low_mi_files}")
    print(f"  High-CC funcs (D/E/F)      : {summary.high_complexity_functions}")
    print("  CC grades (all files)      :")
    for grade in sorted(summary.cc_grade_counts):
        print(f"    {grade}: {summary.cc_grade_counts[grade]}")

    print(f"\n  Total functions            : {summary.total_functions}")
    print(f"  Typed functions            : {summary.typed_functions}")
    print(f"  Typing coverage (functions): {summary.typing_coverage:.1f}%")

    print(f"\n  Avg cognitive complexity   : {summary.avg_cognitive_complexity:.1f}")
    print(f"  Max cognitive complexity   : {summary.max_cognitive_complexity}")

    print_hotspots(file_metrics, function_metrics)

    print(
        "\nRun this before and after a training cycle, then diff the JSON "
        "output and hotspot lists for trends."
    )


if __name__ == "__main__":
    main()
