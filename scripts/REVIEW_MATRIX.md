# Review Matrix Workflow

This directory hosts the utilities that maintain the repository review ledger. Use them in the order below whenever you need to refresh coverage.

## 1. Generate / refresh the matrix

```bash
python scripts/generate_review_matrix.py
```

- Discovers every tracked file (`git ls-files`) and writes `project-docs/review-matrix.csv`.
- Preserves any existing notes/status values, so you can rerun it freely after renames or new files.

## 2. Populate automated checkpoints

```bash
python scripts/populate_lint_warnings.py
```

- Runs Ruff via `uvx` and marks each Python file as `clean` or `N issues: CODE,CODE`.
- Non-Python rows are tagged `N/A`.
- Regenerate the matrix first if files were added.

## 3. Inspect in-function imports

```bash
python scripts/list_in_function_imports.py
```

- Static AST scan that prints any `import`/`from … import` located inside a function or method.
- Treat each finding as a refactor candidate; if you must leave one in place (e.g. circular dependency), document it in the CSV.

## 4. Update the review log

Open `project-docs/review-matrix.csv` in your spreadsheet tool of choice and:

1. Set `status` to `completed` (or whatever milestone you use) once a row has been reviewed.
2. Record outcomes in the dedicated columns (`lint_warnings`, `personal_identifiers`, `in_function_imports`, `refactor_opportunities`, etc.).
3. Use the `notes` column for follow-up actions—link GitHub issues or commits where relevant.

## Tips

- Keep the CSV under version control only if you want audit history; otherwise it can remain local in `project-docs/`.
- Because the scripts rely on `uvx`, ensure `uv` is installed (already bundled in the repo’s Docker workflow).
- Add a CI step that runs `generate_review_matrix.py` and `list_in_function_imports.py` to catch drift when new files land.
