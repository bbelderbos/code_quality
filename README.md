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
uv run main.py /path/to/project
```

Use `--json` to get machine-readable output you can diff over time:

```bash
uv run main.py /path/to/project --json > baseline.json
```

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
$ uv run main.py ~/code/search
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

1. Run this once to create a **baseline** for a client repo.
2. After a Pybites training period, run it again.
3. Compare JSON snapshots and hotspot lists to show improvements in:
   - Maintainability Index (especially “watch” files)
   - High-complexity functions
   - Typing coverage
   - Cognitive complexity in key modules.
