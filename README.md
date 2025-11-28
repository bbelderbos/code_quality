# Pybites Code Maintainability Quality Checker

A tool to get a local snapshot of code quality and maintainability, without sending any code to external services.

It uses:

- **radon** for SLOC, cyclomatic complexity, and Maintainability Index (MI)
- **complexipy** for cognitive complexity
- **AST** analysis for basic type-hint coverage (% of functions with annotations)

## Installation

```bash
git clone git@github.com:bbelderbos/code_quality.git
cd code_quality
uv sync
```

## Usage

```bash
uv run quality.py /path/to/project
```

Use `--json` to get machine-readable output you can diff over time:

```bash
uv run quality.py /path/to/project --json > baseline.json
```

TODO: add diff'ing to see how code quality has changed over time.

## What the metrics mean

- **MI (Maintainability Index)**  
  Heuristic score combining lines of code, complexity, Halstead metrics, and comments.
  We use these bands:

  - `< 60` → **watch** (keep an eye on these files)
  - `60–80` → **moderate**
  - `> 80` → **high**

  Use MI to compare files and track trends over time, not as an absolute judgement.

- **Cognitive complexity**  
  Sonar-style measure of how hard a function is to understand (nesting, branches, etc.).  
  Rule of thumb: keep per-function cognitive complexity **≤ 15**.
  Related: [Pybites Podcast 196: Robin Quintero on Complexipy](https://www.youtube.com/watch?v=plYStC24uwU)

- **Typing coverage**  
  Percentage of functions that have *any* type annotations (args and/or return).

## Example output

```text
$ uv run quality.py ~/code/search
Pybites maintainability snapshot for: /Users/bbelderbos/code/search
  Files scanned              : 16
  Total SLOC                 : 591
  Avg SLOC per file          : 36.9
  Avg MI (all files)         : 68.4  (<60 = watch, 60–80 = moderate, >80 = high)
  Note: MI is a heuristic; use it to compare files and track trends, not as an absolute judgement.
  Files with low MI (<60)    : 10
  High-CC funcs (D/E/F)      : 0
  CC grades (all files)      :
    A: 44
    B: 1
    C: 1

  Total functions            : 37
  Typed functions            : 21
  Typing coverage (functions): 56.8%

  Avg cognitive complexity   : 2.5
  Max cognitive complexity   : 7

Top 5 lowest MI files (MI < 60.0 = watch, >= 80.0 = high):
   54.0 [WATCH]  src/pybites_search/base.py
   55.6 [WATCH]  src/pybites_search/all_content.py
   60.1 [OK]  src/pybites_search/youtube.py
   60.1 [OK]  src/pybites_search/podcast.py
   60.2 [OK]  src/pybites_search/bite.py

Top 5 most complex functions (target cognitive complexity <= 15):
    7 [OK]  tests/test_tip.py:54  test_show_tip_matches
    4 [OK]  src/pybites_search/all_content.py:24  AllSearch::show_matches
    4 [OK]  src/pybites_search/base.py:46  PybitesSearch::show_matches
    3 [OK]  tests/test_all_content.py:82  test_all_search_show_matches
    3 [OK]  src/pybites_search/youtube.py:11  YouTubeSearch::match_content

Run this before and after a training cycle, then diff the JSON output and hotspot lists for trends.
```

## Typical Pybites use

1. Run this once to create a **baseline** for a target repo.
2. After a Pybites training period, run it again.
3. Compare JSON snapshots and hotspot lists to show improvements in:
   - Maintainability Index (especially “watch” files)
   - High-complexity functions
   - Typing coverage
   - Cognitive complexity in key modules.

## Exit code

You can make the script fail (exit code != 0) based on thresholds using these options:

```text
$ uv run quality.py --help
...
  --fail-mi-below FAIL_MI_BELOW
                        Fail if average MI is below this value
  --fail-typing-below FAIL_TYPING_BELOW
                        Fail if typing coverage (functions) is below this value
```

If the average MI is below `mi_threshold` or typing coverage is below `typing_threshold`, the script will exit with code 1.

You can either specify these thresholds via command-line arguments or set them as environment variables: `PYBITES_QUALITY_FAIL_MI_BELOW` and `PYBITES_QUALITY_FAIL_TYPING_BELOW`.

If neither are used, we default to a `MI_LOW` of 60 and a `TYPING_TARGET` of 80.

## Pre-commit integration

Add this to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pybites/code_quality
    rev: v0.1.0
    hooks:
      - id: pybites-quality
        args: ["--fail-mi-below", "60", "--fail-typing-below", "80"]
```

Or leave `args` off if you want to control these by env vars or just use the script defaults.

**Note:** By default, the hook scans the current directory (`.`) which means the entire repository is scanned on every commit. For large repositories, this may be slow. You can customize the scanned directory by adding a path argument:

```yaml
# Only scan the src directory
args: ["src", "--fail-mi-below", "60", "--fail-typing-below", "80"]

# Explicitly scan current directory (same as default)
args: [".", "--fail-mi-below", "60"]
```

Then run:

```bash
uvx pre-commit install
```

Now it should run on each commit, preventing commits that lower code quality below your thresholds.

