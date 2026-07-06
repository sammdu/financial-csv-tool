---
name: financial_csv_tool
description: General-purpose command-line transformer for financial and transaction CSV exports (bank, card, vendor billing). Use when an agent needs to reshape such a CSV into the columns a target importer expects, trim metadata lines wrapped around the header, rename, split, coalesce, or concatenate columns, reformat dates or filter rows by date range, expand flat rows into grouped debit/credit subentry rows, or emit a target template's header.
---

# financial_csv_tool

A single PEP 723 self-contained uv script: `scripts/financial_csv_tool.py`. Run it from this skill directory with `uv run scripts/financial_csv_tool.py INPUT [flags]`.

## Flag reference

`uv run scripts/financial_csv_tool.py --help` is the authoritative flag list. Do not rely on this skill for per-flag details; it documents only what `--help` cannot convey.

## Processing order

Transforms run in a fixed order regardless of flag order on the command line:

1. Parse input: `--skip-lines-start`/`--skip-lines-end`, delimiter, cell stripping
2. `--group-by` with `--agg` and `--collapse`
3. `--rename`
4. `--split`
5. `--date`
6. Date-range filtering
7. `--coalesce`, then `--concat`
8. `--expand` (also runs when `--group-by` is given without `--collapse`, laying out each group as a top entry with continuation rows)
9. Column selection (`--template`, `--keep`, `--drop`) and `--require` checks

Consequences:

- `--group-by` and `--agg` reference original input column names; they run before `--rename`. The group key is tracked through renames for the expand step.
- `--split`, `--date`, `--coalesce`, `--concat`, and `--expand` reference post-rename names and may consume columns created by earlier steps (a `--concat` source can be a `--date` output, an `--expand` amount can be a `--split` output).
- `--keep`, `--drop`, and `--require` see the final post-transform columns.

## Skip-lines symmetry

Exports wrapped in metadata take `--skip-lines-start N` for lines before the real header and `--skip-lines-end M` for trailer lines after the data. Both count physical lines. Blank lines inside the data are dropped automatically and need no skipping.

## Input and output

- Input `-` (or omitting the argument) reads `STDIN`; output then goes to stdout unless `-o` is given.
- A file input without `-o` writes `<input stem>.transformed.csv` next to the input.
- Output reuses the input delimiter, so a tab-separated input stays tab-separated.

## Keep transforms minimal

Preserve source columns and add as few new ones as possible. Only trim columns (`--keep`, `--drop`, `--template`) when the downstream importer requires a fixed header.

## Stay context-agnostic

The tool is vendor-, business-, and importer-agnostic: all vendor-, business-, and importer-specific choices belong in command-line flags, never in its code. Usage of this skill is context-agnostic too; accounting treatment and target-system conventions belong to downstream skills.

## Examples

Split a signed amount column into Deposit and Withdrawal by sign:

```sh
uv run scripts/financial_csv_tool.py statement.csv --split from=Amount to=Deposit,Withdrawal by=sign
```

Skip a 4-line preamble and a 2-line footer around the real header, normalizing the date column:

```sh
uv run scripts/financial_csv_tool.py export.csv --skip-lines-start 4 --skip-lines-end 2 --date "Date=Posted Date"
```

## Verification

After transforming a financial statement, reconcile the output against the source: row count and per-amount-column sums must match to the cent. Report intentional exclusions, such as rows removed by date-range filtering or skipped lines, together with their totals.
