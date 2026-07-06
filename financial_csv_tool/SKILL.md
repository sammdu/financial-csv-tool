---
name: financial_csv_tool
description: General-purpose command-line transformer for financial and transaction CSV exports (bank, card, vendor billing). Use when an agent needs to filter, map, reshape, group, or conditionally expand statement rows into a target import schema.
---

# financial_csv_tool

A single PEP 723 self-contained uv script: `scripts/financial_csv_tool.py`. Run it from this skill directory with `uv run scripts/financial_csv_tool.py INPUT [flags]`.

## Flag reference

`uv run scripts/financial_csv_tool.py --help` is the authoritative flag list. Do not rely on this skill for per-flag details; it documents only what `--help` cannot convey.

## Processing order

Transforms run in a fixed order regardless of flag order on the command line:

1. Parse input: `--skip-lines-start`/`--skip-lines-end`, delimiter, cell stripping
2. Exact-value row filtering with `--where`
3. `--group-by` with `--group` and `--group-collapse`
4. `--rename`
5. `--split`
6. `--map`
7. `--date`
8. Date-range filtering
9. `--coalesce`, then `--concat`
10. `--expand`, selected by `--expand-by` when present (also runs when `--group-by` is given without `--group-collapse`, laying out each group as a top entry with continuation rows)
11. Column selection (`--template`, `--keep`, `--drop`) and `--require` checks

Consequences:

- `--group-by` and `--group` reference original input column names; they run before `--rename`. The group key is tracked through renames for the expand step.
- `--split`, `--date`, `--coalesce`, `--concat`, and `--expand` reference post-rename names and may consume columns created by earlier steps (a `--concat` source can be a `--date` output, an `--expand` amount can be a `--split` output).
- `--map "OUT=COL" "SOURCE=OUTPUT" ...` maps every retained source value and fails on unmapped values.
- `--concat-sep "OUT=SEP"` overrides the separator for one `--concat` output; repeat it for other outputs. Unspecified outputs use a space, and an empty `SEP` joins fields directly.
- `--expand-by COL` selects rules written as `VALUE=AMOUNT_COL[,COL...]=ACCOUNT:side`; `*` selects every row.
- `--keep`, `--drop`, and `--require` see the final post-transform columns.

## Group and expand

- `--group-by COL` reduces rows sharing a key. Repeat `--group "OUT=COL[,COL...]"` for derived values, choose the reducer with `--group-type`, and add `--group-collapse` when only the first row of each group should remain.
- `--expand` turns one row into multiple lines. Without `--expand-by`, rules use `AMOUNT_COL[,COL...]=ACCOUNT:side` and apply to every row.
- `--expand-by COL` selects rules by field value. Rules use `VALUE=AMOUNT_COL[,COL...]=ACCOUNT:side`; use `*` for a rule shared by every value.
- Grouping and expansion may be combined: grouping establishes parent-entry boundaries and values, then expansion emits their child lines.

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

Keep only rows with a specific transaction type:

```sh
uv run scripts/financial_csv_tool.py statement.csv --where "Type=Payment"
```

Map source values and select matching expansion rules:

```sh
uv run scripts/financial_csv_tool.py activity.csv --map "Entry Type=Type" "Charge=Journal Entry" "Payment=Bank Entry" --expand-by Type --expand "Charge=Amount=Expense:debit" --expand "Payment=Amount=Bank:credit"
```

Skip a 4-line preamble and a 2-line footer around the real header, normalizing the date column:

```sh
uv run scripts/financial_csv_tool.py export.csv --skip-lines-start 4 --skip-lines-end 2 --date "Date=Posted Date"
```

## Verification

After transforming a financial statement, reconcile the output against the source: row count and per-amount-column sums must match to the cent. Report intentional exclusions, such as rows removed by date-range filtering or skipped lines, together with their totals.
