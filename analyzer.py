"""
analyzer.py — understands an unknown table and runs analysis "plans" on it.

Nothing in this file knows any column name in advance. Everything is worked
out from the uploaded data itself.

A "plan" is a small dictionary such as:
    {"op": "aggregate", "agg": "sum", "value": "Revenue", "group": "Region"}

Only the operations listed in ALLOWED_OPS can run, so no code written by a
user or by an AI is ever executed.
"""
import io
import json
import re
import warnings

import pandas as pd

ALLOWED_OPS = {
    "aggregate", "count_unique", "trend", "outliers", "missing",
    "correlation", "distribution", "head", "insights",
}
ALLOWED_AGGS = {"sum", "mean", "median", "max", "min", "count"}
AGG_WORDS = {
    "sum": "total", "mean": "average", "median": "median",
    "max": "highest", "min": "lowest", "count": "count of",
}
MAX_TABLE_ROWS = 20


class PlanError(Exception):
    """A question that cannot be answered from this dataset."""


class TableError(Exception):
    """A file that cannot be used as a dataset."""


# Number columns people usually ask about first, and ones that should be
# averaged rather than added up (adding everyone's age means nothing).
KEY_MEASURE_WORDS = {
    "revenue", "sales", "sale", "amount", "cost", "price", "profit", "income", "salary",
    "fee", "fees", "bill", "spend", "total", "payment", "value", "marks", "mark", "score",
}
AVERAGE_WORDS = {
    "age", "rate", "ratio", "percent", "percentage", "pct", "score", "grade", "rating",
    "temperature", "temp", "height", "weight", "bmi", "price", "year",
}


def _words(name):
    return set(re.sub(r"[^a-z0-9]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", name).lower()).split())


# ---------------------------------------------------------------- loading

def load_table(filename, raw):
    """Read CSV or Excel bytes into a cleaned DataFrame."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("csv", "xlsx", "xls"):
        raise TableError("Please upload a .csv, .xlsx or .xls file.")
    try:
        if ext == "csv":
            try:
                df = pd.read_csv(io.BytesIO(raw))
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(raw), encoding="latin-1")
            if len(df.columns) == 1 and ";" in str(df.columns[0]):
                df = pd.read_csv(io.BytesIO(raw), sep=";", encoding="latin-1")
        else:
            df = pd.read_excel(io.BytesIO(raw))
    except Exception:
        raise TableError(f"I couldn't read that file. Please check it is a valid {ext.upper()} file.")

    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if df.empty or len(df.columns) == 0:
        raise TableError("This file has no data rows.")

    for col in df.columns:
        if not (pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col])):
            continue
        as_number = _try_numbers(df[col])
        if as_number is not None:
            df[col] = as_number
            continue
        as_date = _try_dates(df[col])
        if as_date is not None:
            df[col] = as_date
    return df


def _try_numbers(s):
    """Turn text like "$1,200" or "45%" into numbers when most values fit."""
    filled = s.dropna()
    if filled.empty:
        return None
    stripped = s.astype(str).str.replace(r"[$,%₹€£\s]", "", regex=True)
    parsed = pd.to_numeric(stripped.where(s.notna()), errors="coerce")
    return parsed if parsed.notna().sum() >= 0.9 * len(filled) else None


def _try_dates(s):
    filled = s.dropna().astype(str)
    if filled.empty:
        return None
    looks_like_date = filled.head(50).str.contains(
        r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|[A-Za-z]{3,}\s+\d", regex=True
    )
    if looks_like_date.mean() < 0.8:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(s, errors="coerce")
    return parsed if parsed.notna().sum() >= 0.8 * len(filled) else None


# ----------------------------------------------------------------- schema

def _is_id_like(name):
    n = name.lower().strip()
    return bool(re.search(r"(^|[_\s])id$", n)) or name.endswith("ID") or n in ("index", "sno", "s.no", "serial")


def detect_schema(df, filename):
    """Describe every column: its kind, missing values and unique values."""
    details, numeric, categorical, dates = [], [], [], []
    rows = len(df)
    for col in df.columns:
        s = df[col]
        unique = int(s.nunique(dropna=True))
        if pd.api.types.is_datetime64_any_dtype(s):
            kind = "date"
            dates.append(col)
        elif pd.api.types.is_bool_dtype(s):
            kind = "categorical"
            categorical.append(col)
        elif pd.api.types.is_numeric_dtype(s):
            kind = "numeric"
            numeric.append(col)
        elif unique <= 50 or unique < 0.5 * rows:
            kind = "categorical"
            categorical.append(col)
        else:
            kind = "text"
        details.append({
            "name": col, "kind": kind, "dtype": str(s.dtype),
            "missing": int(s.isna().sum()), "unique": unique,
        })

    measures = [c for c in numeric if not _is_id_like(c)] or list(numeric)
    measures.sort(key=lambda c: 0 if _words(c) & KEY_MEASURE_WORDS else 1)
    return {
        "filename": filename,
        "rows": rows,
        "columns": list(df.columns),
        "numeric_columns": numeric,
        "categorical_columns": categorical,
        "date_columns": dates,
        "measure_columns": measures,
        "average_columns": [c for c in measures if _words(c) & AVERAGE_WORDS],
        "missing_values": int(df.isna().sum().sum()),
        "column_details": details,
    }


# ---------------------------------------------------------------- helpers

def fmt(x):
    if x is None or pd.isna(x):
        return "n/a"
    x = float(x)
    return f"{x:,.0f}" if x == int(x) else f"{x:,.2f}"


def _num(x):
    return None if pd.isna(x) else round(float(x), 4)


def _records(df, limit=MAX_TABLE_ROWS):
    out = df.head(limit).copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records"))


def _chart(traces, title, x_label="", y_label=""):
    return {
        "data": traces,
        "layout": {"title": {"text": title}, "xaxis": {"title": {"text": x_label}}, "yaxis": {"title": {"text": y_label}}},
    }


def _proof(operation, columns, rows_used):
    return {"operation": operation, "columns": [c for c in columns if c], "rows_used": int(rows_used)}


def _need_measure(plan, schema):
    """The number column to calculate on, or a clear error if it is unclear."""
    if plan["value"]:
        if plan["value"] not in schema["numeric_columns"]:
            raise PlanError(f'"{plan["value"]}" is not a number column, so I can\'t do maths on it.')
        return plan["value"]
    measures = schema["measure_columns"]
    if not measures:
        raise PlanError("This dataset has no number columns, so I can't calculate that.")
    plan["assumed"] = measures[0]
    return measures[0]


def _default_agg(schema, column):
    return "mean" if column in schema["average_columns"] else "sum"


# ------------------------------------------------------------- validation

def validate_plan(plan, schema):
    """Check a plan against the real dataset before anything runs."""
    if not isinstance(plan, dict) or plan.get("op") not in ALLOWED_OPS:
        reason = plan.get("reason") if isinstance(plan, dict) else None
        raise PlanError(reason or (
            "I couldn't work out how to answer that from this dataset. "
            'Try something like "total <number column>", "top 5 <category>", '
            '"monthly trend", "outliers" or "give me insights".'
        ))

    by_lower = {c.lower(): c for c in schema["columns"]}
    clean = {"op": plan["op"]}
    for key in ("value", "value2", "group", "date"):
        raw = plan.get(key)
        if raw in (None, "", "null"):
            clean[key] = None
            continue
        real = by_lower.get(str(raw).lower().strip())
        if real is None:
            raise PlanError(f'There is no column called "{raw}". Columns here: {", ".join(schema["columns"])}.')
        clean[key] = real

    if clean["date"] and clean["date"] not in schema["date_columns"]:
        raise PlanError(f'"{clean["date"]}" is not a date column.')

    clean["agg"] = plan.get("agg") if plan.get("agg") in ALLOWED_AGGS else None
    clean["order"] = "asc" if plan.get("order") == "asc" else "desc"
    clean["period"] = plan.get("period") if plan.get("period") in ("day", "month", "year") else None
    try:
        clean["n"] = max(1, min(50, int(plan.get("n")))) if plan.get("n") is not None else None
    except (TypeError, ValueError):
        clean["n"] = None
    return clean


# ------------------------------------------------------------- operations

def _aggregate(df, schema, plan):
    agg, group = plan["agg"], plan["group"]

    if not group:
        if agg == "count" and not plan["value"]:
            return {
                "answer": f"This dataset has **{len(df):,}** rows.",
                "proof": _proof("Counted every row", [], len(df)),
            }
        value = _need_measure(plan, schema)
        agg = agg or _default_agg(schema, value)
        used = df[value].dropna()
        result = used.agg(agg)
        return {
            "answer": f"The {AGG_WORDS[agg]} **{value}** is **{fmt(result)}** (from {len(used):,} rows).",
            "proof": _proof(f"{agg} of {value}", [value], len(used)),
        }

    if agg == "count" or (not plan["value"] and not schema["measure_columns"]):
        series = df[group].value_counts()
        label, value, agg = "Rows", None, "count"
        used = int(df[group].notna().sum())
    else:
        value = _need_measure(plan, schema)
        agg = agg or _default_agg(schema, value)
        series = df.groupby(group)[value].agg(agg).dropna()
        label = f"{AGG_WORDS[agg].capitalize()} {value}"
        used = int(df[[group, value]].dropna().shape[0])

    if series.empty:
        raise PlanError(f'There is nothing to compare in "{group}".')
    ascending = plan["order"] == "asc"
    series = series.sort_values(ascending=ascending)
    n = plan["n"] or 10
    top = series.head(n)
    names = [str(k) for k in top.index]
    side = "lowest" if ascending else "highest"

    if n == 1 and value is None:
        answer = f"**{names[0]}** has the {'fewest' if ascending else 'most'} rows: **{fmt(top.iloc[0])}** (out of {len(series)} {group} values)."
    elif n == 1:
        answer = f"**{names[0]}** has the {side} {label.lower()}: **{fmt(top.iloc[0])}** (out of {len(series)} {group} values)."
    else:
        answer = (
            f"{'Bottom' if ascending else 'Top'} {len(top)} **{group}** by {label.lower()}. "
            f"#1 is **{names[0]}** with **{fmt(top.iloc[0])}**."
        )
    shown = series.head(max(n, 10))
    return {
        "answer": answer,
        "table": [{group: str(k), label: _num(v)} for k, v in top.items()],
        "chart": _chart(
            [{"type": "bar", "x": [str(k) for k in shown.index], "y": [_num(v) for v in shown.values]}],
            f"{label} by {group}", group, label,
        ),
        "proof": _proof(f"Grouped by {group}, {agg} of {value or 'rows'}, sorted {side} first", [group, value], used),
    }


def _count_unique(df, schema, plan):
    col = plan["group"] or plan["value"]
    if not col:
        return _aggregate(df, schema, dict(plan, agg="count", group=None, value=None))
    unique = int(df[col].nunique())
    return {
        "answer": f"There are **{unique:,}** different **{col}** values across {len(df):,} rows.",
        "proof": _proof(f"Counted unique values of {col}", [col], int(df[col].notna().sum())),
    }


def _trend(df, schema, plan):
    date_col = plan["date"] or (schema["date_columns"][0] if schema["date_columns"] else None)
    if not date_col:
        raise PlanError("I can't show a trend because this dataset has no date column.")
    data = df.dropna(subset=[date_col])
    span_days = (data[date_col].max() - data[date_col].min()).days
    period = plan["period"] or ("day" if span_days <= 62 else "year" if span_days > 365 * 4 else "month")
    keys = data[date_col].dt.to_period({"day": "D", "month": "M", "year": "Y"}[period])

    counting = plan["agg"] == "count" or (not plan["value"] and not schema["measure_columns"])
    if counting:
        series, label, value, agg = data.groupby(keys).size(), "Rows", None, "count"
    else:
        value = _need_measure(plan, schema)
        agg = plan["agg"] or _default_agg(schema, value)
        series = data.groupby(keys)[value].agg(agg).dropna()
        label = f"{AGG_WORDS[agg].capitalize()} {value}"
    if len(series) < 2:
        raise PlanError(f"There is only one {period} of data, so there is no trend to show.")

    first, last = series.iloc[0], series.iloc[-1]
    change = f"{(last - first) / abs(first) * 100:+.1f}%" if first else "n/a"
    direction = "rose" if last > first else "fell" if last < first else "stayed flat"
    answer = (
        f"{label} per {period} {direction} from **{fmt(first)}** ({series.index[0]}) to **{fmt(last)}** "
        f"({series.index[-1]}), a change of **{change}**. The peak was **{fmt(series.max())}** in {series.idxmax()}."
    )
    x = [str(p) for p in series.index]
    return {
        "answer": answer,
        "table": [{period.capitalize(): k, label: _num(v)} for k, v in zip(x, series.values)],
        "chart": _chart([{"type": "scatter", "mode": "lines+markers", "x": x, "y": [_num(v) for v in series.values]}],
                        f"{label} per {period}", period.capitalize(), label),
        "proof": _proof(f"Grouped {date_col} by {period}, {agg} of {value or 'rows'}", [date_col, value], len(data)),
    }


def _outlier_mask(s):
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    low, high = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    return (s < low) | (s > high), low, high


def _outliers(df, schema, plan):
    columns = [_need_measure(plan, schema)] if plan["value"] else schema["measure_columns"]
    if not columns:
        raise PlanError("This dataset has no number columns to check for outliers.")
    lines, first_hit = [], None
    for col in columns:
        mask, low, high = _outlier_mask(df[col])
        count = int(mask.sum())
        if count:
            lines.append(f"**{col}**: {count} unusual value(s) outside the normal range {fmt(low)} to {fmt(high)}.")
            first_hit = first_hit or (col, mask)
    if not first_hit:
        return {
            "answer": f"No outliers found in {', '.join(columns)}. Every value sits inside the normal range.",
            "proof": _proof("IQR rule: flag values beyond 1.5 x the middle 50% spread", columns, len(df)),
        }
    col, mask = first_hit
    rows = df[mask].sort_values(col, ascending=False)
    return {
        "answer": "\n".join(lines) + f"\nThe table shows the unusual rows for {col}.",
        "table": _records(rows),
        "chart": _chart([{"type": "box", "y": [_num(v) for v in df[col].dropna()], "name": col, "boxpoints": "outliers"}],
                        f"Spread of {col}", "", col),
        "proof": _proof("IQR rule: flag values beyond 1.5 x the middle 50% spread", columns, len(df)),
    }


def _missing(df, schema, plan):
    counts = df.isna().sum()
    counts = counts[counts > 0].sort_values(ascending=False)
    proof = _proof("Counted empty cells in every column", [], len(df))
    if counts.empty:
        return {"answer": "No missing values. Every cell in this dataset is filled.", "proof": proof}
    return {
        "answer": f"There are **{int(counts.sum())}** missing values in {len(counts)} column(s). Most are in **{counts.index[0]}** ({int(counts.iloc[0])}).",
        "table": [{"Column": c, "Missing": int(v), "Percent": round(v / len(df) * 100, 1)} for c, v in counts.items()],
        "chart": _chart([{"type": "bar", "x": list(counts.index), "y": [int(v) for v in counts.values]}],
                        "Missing values per column", "Column", "Missing"),
        "proof": proof,
    }


def _correlation(df, schema, plan):
    cols = schema["measure_columns"]
    if len(cols) < 2:
        raise PlanError("I need at least two number columns to look for a relationship.")
    corr = df[cols].corr()
    pairs = [(a, b, corr.loc[a, b]) for i, a in enumerate(cols) for b in cols[i + 1:] if pd.notna(corr.loc[a, b])]
    if not pairs:
        raise PlanError("There isn't enough data to measure a relationship.")
    pairs.sort(key=lambda p: abs(p[2]), reverse=True)
    asked = [c for c in (plan["value"], plan["value2"]) if c in cols]
    matching = [p for p in pairs if all(c in p[:2] for c in asked)]
    a, b, r = (matching or pairs)[0]
    lead = "The link" if len(asked) == 2 and matching else "The strongest link"
    strength = "strong" if abs(r) >= 0.7 else "moderate" if abs(r) >= 0.4 else "weak" if abs(r) >= 0.1 else "almost none"
    way = "rise together" if r > 0 else "move in opposite directions"
    meaning = f"they tend to {way}" if abs(r) >= 0.1 else "one tells you almost nothing about the other"
    return {
        "answer": f"{lead} is between **{a}** and **{b}** (correlation {r:.2f}, {strength}): {meaning}. This shows a pattern, not a cause.",
        "table": [{"Column A": x, "Column B": y, "Correlation": round(float(v), 2)} for x, y, v in pairs[:10]],
        "chart": _chart([{"type": "heatmap", "x": cols, "y": cols, "z": [[_num(v) for v in row] for row in corr.values],
                          "zmin": -1, "zmax": 1, "colorscale": "RdBu"}], "Correlation between number columns"),
        "proof": _proof("Pearson correlation between every pair of number columns", cols, len(df)),
    }


def _distribution(df, schema, plan):
    col = plan["group"] or plan["value"] or (schema["categorical_columns"] or schema["measure_columns"] or [None])[0]
    if not col:
        raise PlanError("I couldn't tell which column you want the breakdown of.")
    s = df[col].dropna()
    if col in schema["numeric_columns"]:
        return {
            "answer": f"**{col}** ranges from {fmt(s.min())} to {fmt(s.max())}. The average is {fmt(s.mean())} and the middle value is {fmt(s.median())}.",
            "chart": _chart([{"type": "histogram", "x": [_num(v) for v in s]}], f"Distribution of {col}", col, "Rows"),
            "proof": _proof(f"Histogram and summary of {col}", [col], len(s)),
        }
    counts = s.astype(str).value_counts().head(plan["n"] or 10)
    share = counts.iloc[0] / len(s) * 100
    trace = ({"type": "pie", "labels": list(counts.index), "values": [int(v) for v in counts.values]}
             if len(counts) <= 6 else {"type": "bar", "x": list(counts.index), "y": [int(v) for v in counts.values]})
    return {
        "answer": f"**{col}** has {s.nunique()} different values. The most common is **{counts.index[0]}** ({int(counts.iloc[0])} rows, {share:.0f}%).",
        "table": [{col: k, "Rows": int(v)} for k, v in counts.items()],
        "chart": _chart([trace], f"Breakdown of {col}", col, "Rows"),
        "proof": _proof(f"Counted rows for each {col}", [col], len(s)),
    }


def _head(df, schema, plan):
    n = plan["n"] or 5
    return {
        "answer": f"Here are the first {min(n, len(df))} rows of {len(df):,}.",
        "table": _records(df, n),
        "proof": _proof("Showed rows as they appear in the file", [], min(n, len(df))),
    }


def auto_insights(df, schema, limit=5):
    """Plain-English observations worked out from the data alone."""
    out = [
        f"The dataset has **{schema['rows']:,} rows** and **{len(schema['columns'])} columns**: "
        f"{len(schema['numeric_columns'])} number, {len(schema['categorical_columns'])} category, {len(schema['date_columns'])} date."
    ]
    measures = schema["measure_columns"]
    if measures:
        m = measures[0]
        s = df[m].dropna()
        if len(s):
            additive = m not in schema["average_columns"]
            if additive:
                out.append(f"**{m}** totals **{fmt(s.sum())}**, averaging {fmt(s.mean())} per row (range {fmt(s.min())} to {fmt(s.max())}).")
            else:
                out.append(f"**{m}** averages **{fmt(s.mean())}** (range {fmt(s.min())} to {fmt(s.max())}).")
            if schema["categorical_columns"]:
                c = schema["categorical_columns"][0]
                by = df.groupby(c)[m].agg("sum" if additive else "mean").sort_values(ascending=False)
                if len(by) > 1 and additive and s.sum() > 0 and s.min() >= 0:
                    out.append(f"**{by.index[0]}** leads **{c}** with {by.iloc[0] / s.sum() * 100:.0f}% of total {m}; {by.index[-1]} is lowest.")
                elif len(by) > 1:
                    out.append(f"**{by.index[0]}** has the highest average {m} in **{c}** ({fmt(by.iloc[0])}); {by.index[-1]} has the lowest ({fmt(by.iloc[-1])}).")
            if schema["date_columns"]:
                try:
                    out.append(_trend(df, schema, {"date": None, "value": m, "agg": None, "period": None})["answer"])
                except PlanError:
                    pass
            mask, _, _ = _outlier_mask(s)
            if mask.sum():
                out.append(f"**{m}** has {int(mask.sum())} unusual value(s) far from the rest. Worth a closer look.")
    if schema["missing_values"]:
        out.append(f"There are **{schema['missing_values']}** missing values that could affect totals and averages.")
    return out[:limit]


def _insights(df, schema, plan):
    items = auto_insights(df, schema, plan["n"] or 5)
    return {
        "answer": "\n".join(f"{i}. {text}" for i, text in enumerate(items, 1)),
        "proof": _proof("Summary statistics on every column", [], len(df)),
    }


OPERATIONS = {
    "aggregate": _aggregate, "count_unique": _count_unique, "trend": _trend,
    "outliers": _outliers, "missing": _missing, "correlation": _correlation,
    "distribution": _distribution, "head": _head, "insights": _insights,
}


def run_plan(df, schema, plan):
    """Validate a plan, run it, and return answer + table + chart + proof."""
    clean = validate_plan(plan, schema)
    result = OPERATIONS[clean["op"]](df, schema, clean)
    assumed = clean.pop("assumed", None)
    if assumed and len(schema["measure_columns"]) > 1:
        result["answer"] += f" (You didn't name a number column, so I used {assumed}.)"
    result["proof"]["plan"] = {k: v for k, v in clean.items() if v is not None}
    return result


def suggest_questions(schema):
    """Starter questions built from this dataset's own column names."""
    num = (schema["measure_columns"] or [None])[0]
    cats = schema["categorical_columns"]
    out = []
    if num:
        out.append(f"What is the total {num}?")
        if cats:
            out.append(f"Which {cats[0]} has the highest {num}?")
            out.append(f"Show the top 5 {cats[-1]} by average {num}")
            if len(schema["measure_columns"]) > 1:
                out.append(f"Is {schema['measure_columns'][1]} related to {num}?")
        if schema["date_columns"]:
            out.append(f"What is the monthly trend of {num}?")
        out.append(f"Are there any outliers in {num}?")
    elif cats:
        out.append(f"Show the breakdown of {cats[0]}")
    out.append("Give me 3 important insights")
    return out
