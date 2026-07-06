#!/usr/bin/env -S uv run -s
# /// script
# requires-python = ">=3.12"
# ///
"""
General-purpose, vendor-agnostic, context-agnostic transformer for financial statement CSVs
(bank, card, vendor billing/receipts): reshapes any export into the columns a target importer
expects. Keep vendor-, business-, and system-specific choices in command-line flags, never in
this code.
"""
import argparse
import csv
import sys
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path


def exit_with_error(message):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def csv_items(value):
    try:
        return [item.strip() for item in next(csv.reader([value], skipinitialspace=True)) if item.strip()]
    except csv.Error as error:
        exit_with_error(f"invalid comma-separated value {value!r}: {error}")


def parse_options(values, allowed, required=()):
    pairs = [Field.pair(value) for value in values]
    duplicates = [key for key, _ in pairs if sum(name == key for name, _ in pairs) > 1]
    unknown = [key for key, _ in pairs if key not in allowed]
    missing = [key for key in required if key not in dict(pairs)]
    if duplicates:
        exit_with_error(f"duplicate option(s): {', '.join(dict.fromkeys(duplicates))}")
    if unknown:
        exit_with_error(f"unknown option(s): {', '.join(dict.fromkeys(unknown))}")
    if missing:
        exit_with_error(f"missing option(s): {', '.join(missing)}")
    return dict(pairs)


class Field:
    DATE_FORMATS = ["%Y%m%d", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%m-%d-%Y", "%d-%m-%Y"]
    FORMATTERS = {
        "abs": lambda field: str(abs(field.number())),
        "lower": lambda field: field.value.lower(),
        "strip": lambda field: field.value.strip(),
        "title": lambda field: field.value.title(),
        "upper": lambda field: field.value.upper(),
    }

    def __init__(self, value):
        self.value = value

    @staticmethod
    def pair(value):
        if "=" not in value:
            exit_with_error(f"expected KEY=VALUE, got {value!r}")
        left, right = (side.strip() for side in value.split("=", 1))
        if not left or not right:
            exit_with_error(f"expected non-empty KEY=VALUE, got {value!r}")
        return left, right

    def number(self):
        text = self.value.strip().lstrip("=").replace(",", "").replace('"', "")
        if not text:
            return 0.0
        parenthesized = text.startswith("(") and text.endswith(")")
        text = text.removeprefix("(").removesuffix(")").translate(str.maketrans("", "", "$€£¥"))
        try:
            parsed = float(text)
            return -parsed if parenthesized else parsed
        except ValueError:
            exit_with_error(f"non-numeric value {self.value!r}")

    def split_by_sign(self):
        text = self.value.strip()
        if not text:
            return [Field(""), Field("")]
        if text.startswith("-"):
            return [Field(""), Field(text[1:].strip())]
        return [Field(text.removeprefix("+").strip()), Field("")]

    def parse_date(self, formats, label="date"):
        text = self.value.strip()
        if not text:
            return None
        for fmt in formats:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        exit_with_error(f"unparseable {label} {self.value!r} (tried {', '.join(formats)})")

    def format_date(self, formats, out_format):
        parsed = self.parse_date(formats)
        return parsed.strftime(out_format) if parsed else ""


class Statement:
    def __init__(self, text):
        self.text = text

    @classmethod
    def load(cls, source, encoding):
        text = sys.stdin.read() if str(source) == "-" else Path(source).read_text(encoding=encoding)
        return cls(text)

    @staticmethod
    def dialect_for(lines, delimiter):
        class Dialect(csv.excel):
            pass

        if delimiter != "auto":
            Dialect.delimiter = "\t" if delimiter in ("tab", r"\t") else delimiter
            return Dialect
        try:
            return csv.Sniffer().sniff("\n".join(lines[:25]), delimiters=",;\t|")
        except csv.Error:
            return csv.excel

    def parse(self, delimiter=",", skip_start=0, skip_end=0, strip=True):
        lines = self.text.splitlines()
        lines = lines[skip_start : len(lines) - skip_end]
        dialect, headers, rows = self.dialect_for(lines, delimiter), None, []
        for index, raw in enumerate(csv.reader(lines, dialect), 1 + skip_start):
            if not any(cell.strip() for cell in raw):
                continue
            if headers is None:
                headers = [cell.strip().removeprefix(chr(0xFEFF)) for cell in raw]
                if len(headers) != len(set(headers)):
                    exit_with_error("duplicate headers after trimming")
                continue
            if any(cell.strip() for cell in raw[len(headers) :]):
                exit_with_error(f"row {index} has more cells than headers")
            row = {header: (raw[i] if i < len(raw) else "") for i, header in enumerate(headers)}
            rows.append({header: value.strip() if strip else value for header, value in row.items()})
        if headers is None:
            exit_with_error("input has no rows after --skip-lines-start/--skip-lines-end")
        return Table(headers, rows, dialect)


class Table:
    REDUCERS = {
        "sum": sum,
        "min": min,
        "max": max,
        "mean": lambda v: sum(v) / len(v),
        "count": len,
        "first": lambda v: v[0],
    }

    def __init__(self, headers, rows, dialect):
        self.headers, self.rows, self.dialect = headers, rows, dialect

    def require(self, name, action):
        if name not in self.headers:
            exit_with_error(f"missing {action} column: {name}")
        return name

    def ensure(self, *names):
        self.headers += [name for name in names if name not in self.headers]

    def derive(self, target, function):
        self.ensure(target)
        for row in self.rows:
            row[target] = function(row)

    def rename(self, old, new):
        self.require(old, "rename")
        self.headers = [new if header == old else header for header in self.headers]
        for row in self.rows:
            row[new] = row.pop(old)

    def split(self, values, strip):
        spec = parse_options(values, {"from", "to", "delim", "by", "format"}, {"from", "to"})
        source, targets = spec["from"], csv_items(spec["to"])
        formats = parse_options([item.replace(":", "=", 1) for item in csv_items(spec.get("format", ""))], targets)
        unknown = [name for name in formats.values() if name not in Field.FORMATTERS]
        if unknown:
            exit_with_error(f"unknown format(s): {', '.join(dict.fromkeys(unknown))}")
        delimiter, method = spec.get("delim"), spec.get("by")
        self.require(source, "split")
        if method and method != "sign":
            exit_with_error(f"unknown split method: {method}")
        if method and delimiter is not None:
            exit_with_error("--split accepts either by=sign or delim=SEP, not both")
        if method == "sign" and len(targets) != 2:
            exit_with_error("--split by=sign needs exactly two output columns")
        self.ensure(*targets)
        for row in self.rows:
            parts = (
                Field(row[source]).split_by_sign()
                if method == "sign"
                else [Field(part) for part in row[source].split(delimiter, len(targets) - 1)]
            )
            for index, target in enumerate(targets):
                value = parts[index].value if index < len(parts) else ""
                value = value.strip() if strip else value
                row[target] = Field.FORMATTERS[formats[target]](Field(value)) if target in formats else value

    def combine(self, target, sources, join, strip):
        unknown = [s for s in sources if s not in self.headers and not s.startswith("literal:")]
        if unknown:
            exit_with_error(f"missing source column(s): {', '.join(unknown)}")
        read = lambda row, s: s.removeprefix("literal:") if s.startswith("literal:") else row[s]

        def merge(row):
            values = [read(row, s) for s in sources]
            values = [value.strip() if strip else value for value in values if value.strip()]
            return next(iter(values), "") if join is None else join.join(values)

        self.derive(target, merge)

    def filter_dates(self, field, low, high, formats):
        self.require(field, "date-range-field")
        kept = []
        for row in self.rows:
            when = Field(row[field]).parse_date(formats)
            if when is None:
                exit_with_error(f"unparseable date in --date-range-field {field!r}: {row[field]!r}")
            if (low is None or when >= low) and (high is None or when <= high):
                kept.append(row)
        self.rows = kept

    def group(self, key, specs, agg_type, collapse):
        self.require(key, "group-by")
        for target, sources in specs:
            unknown = [c for c in sources if c not in self.headers]
            if unknown:
                exit_with_error(f"missing agg source column(s): {', '.join(unknown)}")
        self.ensure(*(target for target, _ in specs))
        groups = {}
        for row in self.rows:
            groups.setdefault(row[key], []).append(row)
        reduce, output = self.REDUCERS[agg_type], []
        for rows in groups.values():
            values = {}
            for target, sources in specs:
                value = reduce([sum(Field(row[column]).number() for column in sources) for row in rows])
                values[target] = str(value) if agg_type == "count" else f"{value:.2f}"
            if collapse:
                output.append({**rows[0], **values})
                continue
            for index, row in enumerate(rows):
                row.update({target: value if index == 0 else "" for target, value in values.items()})
            output.extend(rows)
        self.rows = output

    def assemble(self, specs, columns, reverse, group_by=""):
        entries = []
        for amount, rhs in (Field.pair(spec) for spec in specs):
            amounts = csv_items(amount)
            for column in amounts:
                self.require(column, "expand")
            name, _, side = rhs.rpartition(":")
            side = side.strip().lower()
            if not name or side not in ("debit", "credit"):
                exit_with_error(f"--expand needs AMOUNT_COL[,COL...]=ACCOUNT:debit|credit, got {rhs!r}")
            entries.append((amounts, name.strip(), side))
        account, debit, credit = columns[:3]
        if not entries:
            for column in columns:
                self.require(column, "subentry")
        shared = set(columns)
        self.ensure(*columns)
        previous, output = None, []
        for row in self.rows:
            lines = []
            for amounts, name, side in entries:
                amount = sum(Field(row[column]).number() for column in amounts)
                if amount < 0 and not reverse:
                    exit_with_error(
                        f"negative --expand amount {amount}; pass --expand-negative-reverses to reverse accounts"
                    )
                if amount:
                    line_side = ("credit" if side == "debit" else "debit") if amount < 0 else side
                    value = f"{abs(amount):.2f}"
                    lines.append((name, value if line_side == "debit" else "", value if line_side == "credit" else ""))
            if not entries:
                lines.append((row[account], row[debit], row[credit]))
            first = not group_by or row[group_by] != previous
            for name, line_debit, line_credit in lines:
                base = row if first else {c: (row.get(c, "") if c in shared else "") for c in self.headers}
                output.append(
                    {
                        **base,
                        account: name,
                        debit: line_debit,
                        credit: line_credit,
                    }
                )
                first = False
            if lines:
                previous = row.get(group_by)
        self.rows = output

    def transform(self, args, template_headers):
        if args.agg and not args.group_by:
            exit_with_error("--agg requires --group-by")
        if args.collapse and not args.group_by:
            exit_with_error("--collapse requires --group-by")
        if args.group_by:
            specs = [(target, csv_items(sources)) for target, sources in map(Field.pair, args.agg)]
            self.group(args.group_by, specs, args.agg_type, args.collapse)

        group_by = args.group_by
        for old, new in map(Field.pair, args.rename):
            self.rename(old, new)
            group_by = new if group_by == old else group_by
        for values in args.split:
            self.split(values, args.strip_derived)

        formats = [args.in_date_format] if args.in_date_format else Field.DATE_FORMATS
        for target, column in map(Field.pair, args.date):
            self.require(column, "date")
            self.derive(target, lambda row, source=column: Field(row[source]).format_date(formats, args.out_date_format))
        if args.date_range_field:
            low = Field(args.date_range_from).parse_date(formats, "--date-range-from")
            high = Field(args.date_range_to).parse_date(formats, "--date-range-to")
            self.filter_dates(args.date_range_field, low, high, formats)

        for specs, join in ((args.coalesce, None), (args.concat, args.concat_sep)):
            for target, sources in map(Field.pair, specs):
                self.combine(target, csv_items(sources), join, args.strip_derived)

        if args.expand or (args.group_by and not args.collapse):
            columns = csv_items(args.expand_columns)
            if len(columns) < 3:
                exit_with_error(
                    f"--expand-columns needs at least ACCOUNT,DEBIT,CREDIT targets, got {args.expand_columns!r}"
                )
            unknown = [column for column in columns if template_headers and column not in template_headers]
            if unknown:
                exit_with_error("--template is missing expand output column(s): " + ", ".join(unknown))
            self.assemble(args.expand, columns, args.expand_negative_reverses, group_by)

        available = set(self.headers) | set(template_headers)
        missing = [column for column in args.drop + args.keep + args.require if column not in available]
        if missing:
            exit_with_error(f"missing column(s): {', '.join(dict.fromkeys(missing))}")
        output_headers = template_headers or self.headers
        columns = args.keep or [header for header in output_headers if header not in set(args.drop)]
        blank_counts = {column: sum(not row.get(column, "").strip() for row in self.rows) for column in args.require}
        failed = {column: count for column, count in blank_counts.items() if count}
        if failed:
            exit_with_error(
                "blank required values: " + ", ".join(f"{column}={count}" for column, count in failed.items())
            )
        return columns

    def write(self, file, columns):
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore", dialect=self.dialect)
        writer.writeheader()
        writer.writerows(self.rows)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Generic CSV transformer that reshapes transaction exports (bank, card, vendor billing) "
        "into the columns another system expects, including group, expand, and collapse steps.",
    )
    parser.add_argument("input", type=Path, nargs="?", default=Path("-"))
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--template", type=Path, help="CSV template whose header becomes the output columns when --keep is omitted."
    )
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--delimiter", default=",", help="Input delimiter (default comma; use auto to detect).")
    parser.add_argument("--skip-lines-start", type=int, default=0)
    parser.add_argument("--skip-lines-end", type=int, default=0)
    parser.add_argument("--strip-cells", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--strip-derived", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--rename", action="append", default=[], metavar="OLD=NEW")
    parser.add_argument(
        "--split",
        action="append",
        nargs="+",
        default=[],
        metavar="KEY=VALUE",
        help="Split one column into several: from=COL to=OUT1,OUT2 [delim=SEP|by=sign] [format=OUT:FORMAT,...].",
    )
    parser.add_argument("--date", action="append", default=[], metavar="OUT=COL")
    parser.add_argument("--in-date-format", default="")
    parser.add_argument("--out-date-format", default="%Y-%m-%d")
    parser.add_argument("--date-range-field", default="")
    parser.add_argument("--date-range-from", default="")
    parser.add_argument("--date-range-to", default="")
    parser.add_argument("--coalesce", action="append", default=[], metavar="OUT=COL[,COL|literal:TEXT...]")
    parser.add_argument("--concat", action="append", default=[], metavar="OUT=COL[,COL|literal:TEXT...]")
    parser.add_argument("--concat-sep", default=" ")
    parser.add_argument(
        "--group-by",
        default="",
        metavar="COL",
        help="Assemble rows sharing COL under one top entry.",
    )
    parser.add_argument(
        "--agg",
        action="append",
        default=[],
        metavar="OUT=COL[,COL...]",
        help="Put the --agg-type reduction of grouped columns on the first row (summed per row first).",
    )
    parser.add_argument("--collapse", action="store_true", help="Collapse each --group-by group to its first row.")
    parser.add_argument(
        "--agg-type", default="sum", choices=list(Table.REDUCERS), help="Reduction applied by --agg (default sum)."
    )
    parser.add_argument(
        "--expand",
        action="append",
        default=[],
        metavar="AMOUNT_COL[,COL...]=ACCOUNT:debit|credit",
        help="Create one output subentry; repeat to expand each input row into several.",
    )
    parser.add_argument(
        "--expand-columns",
        default="Account,Debit,Credit",
        metavar="ACCOUNT,DEBIT,CREDIT[,OTHER...]",
        help="Output subentry columns; additional columns remain populated on continuation rows.",
    )
    parser.add_argument(
        "--expand-negative-reverses",
        action="store_true",
        help="Reverse debit/credit accounts for negative --expand amounts and write the positive magnitude.",
    )
    parser.add_argument("--drop", action="append", default=[])
    parser.add_argument("--keep", action="append", default=[])
    parser.add_argument("--require", action="append", default=[])
    return parser


def main():
    args = build_parser().parse_args()
    table = Statement.load(args.input, args.encoding).parse(
        args.delimiter, args.skip_lines_start, args.skip_lines_end, args.strip_cells
    )
    template_headers = Statement.load(args.template, args.encoding).parse("auto").headers if args.template else []
    columns = table.transform(args, template_headers)
    output = (
        args.output
        if args.output or str(args.input) == "-"
        else args.input.with_name(f"{args.input.stem}.transformed.csv")
    )
    with output.open("w", encoding="utf-8", newline="") if output else nullcontext(sys.stdout) as file:
        table.write(file, columns)
    print(f"wrote {len(table.rows)} rows to {output or 'stdout'}", file=sys.stderr)


if __name__ == "__main__":
    main()
