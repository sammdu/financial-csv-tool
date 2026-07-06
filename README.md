# financial_csv_tool.py

[`financial_csv_tool.py`](financial_csv_tool/scripts/financial_csv_tool.py) reshapes transaction records and financial CSV statements from banks, credit cards, and vendors. Every transformation is supplied through command-line options.

## Usage

```sh
uv run financial_csv_tool.py INPUT [flags]
```

Pass a CSV file path as `INPUT`. Without `-o`, the transformed rows are written to `<input stem>.transformed.csv` next to the input; pass `-o OUTPUT` to choose the path.

Common operations:

- trim metadata around useful figures
- rename, split, coalesce, concatenate, keep, or drop columns
- filter rows by exact field values or dates
- reduce related rows with grouping or expand rows into conditional debit/credit lines
- adopt a template header and require populated output columns

Run `uv run financial_csv_tool.py --help` for the complete option reference.

Grouping and expansion are complementary: `--group-by` chooses the key used to reduce rows, while `--expand-by` chooses the field used to select expansion rules. Without `--expand-by`, every `--expand` rule applies to every row.

## Examples

Split a signed amount into separate deposit and withdrawal columns (split by sign):

```sh
uv run financial_csv_tool.py statement.csv --split from=Amount to=Deposit,Withdrawal by=sign
```

Split one column on a delimiter and format each output (split by delimiter):

```sh
uv run financial_csv_tool.py contacts.csv --split from=Name to=First,Last delim=" " format=First:title,Last:upper
```

Rename, reformat a date, and keep only the columns an importer needs (column-wise):

```sh
uv run financial_csv_tool.py statement.csv --rename "Txn Date=Date" --date "Posting Date=Date" --keep "Posting Date" --keep Description --keep Amount
```

Concatenate columns into one and fill a field from the first non-blank source (column-wise):

```sh
uv run financial_csv_tool.py statement.csv --concat "Memo=Description,Reference" --coalesce "Party=Payee,literal:Unknown"
```

Set separators per concatenated field; unspecified fields use a space:

```sh
uv run financial_csv_tool.py statement.csv --concat "Signed Amount=Sign,Magnitude" --concat "Memo=Date,Description" --concat-sep "Signed Amount="
```

Filter rows to a date range (row-wise):

```sh
uv run financial_csv_tool.py statement.csv --date-range-field Date --date-range-from 2025-01-01 --date-range-to 2025-03-31
```

Filter rows by an exact field value (row-wise):

```sh
uv run financial_csv_tool.py statement.csv --where "Type=Payment"
```

Group rows by a key and sum a column, collapsing each group to one row:

```sh
uv run financial_csv_tool.py line_items.csv --group-by Category --group "Total=Amount" --group-collapse
```

Expand each transaction into balanced debit and credit rows (row-wise):

```sh
uv run financial_csv_tool.py charges.csv --expand "Amount=Advertising:debit" --expand "Amount=Chequing:credit" --expand-negative-reverses
```

Select expansion rules from a row field:

```sh
uv run financial_csv_tool.py activity.csv \
  --map "Entry Type=Type" "Charge=Journal Entry" "Payment=Bank Entry" \
  --expand-by Type \
  --expand "Charge=Amount=Expense:debit" \
  --expand "Charge=Amount=Payable:credit" \
  --expand "Payment=Amount=Payable:debit" \
  --expand "Payment=Amount=Bank:credit"
```

Transformations always follow the processing order documented in the bundled [skill instructions](./financial_csv_tool/SKILL.md), regardless of option order.

## Dependencies

- [Python 3.12 or later](https://docs.python.org/3.12/)
- [uv](https://docs.astral.sh/uv/)

The script contains PEP 723 metadata, so `uv run` can resolve its dependency without a separate installation step.

## Agentic Skills

The self-contained [`financial_csv_tool` skill](./financial_csv_tool/) can be installed as an Agentic Skill to give compatible agents its processing order, usage constraints, and reconciliation requirements.
