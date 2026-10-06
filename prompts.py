"""
prompts.py — the instructions sent to Claude (only used when an API key is set).

Claude never writes code and never sees the data rows. It receives the column
names and their kinds, and replies with a small JSON "plan". Our own code in
analyzer.py then checks that plan and runs it locally.
"""

PLAN_SYSTEM_PROMPT = """You turn a question about a data table into a JSON analysis plan.

You are given only the table's column names and kinds. You never see the rows,
and you never write code. A separate program validates your plan and runs it.

Reply with one JSON object and nothing else:

{
  "op": "aggregate | count_unique | trend | outliers | missing | correlation | distribution | head | insights | unknown",
  "agg": "sum | mean | median | max | min | count | null",
  "value": "exact name of a numeric column, or null",
  "value2": "correlation only: the second numeric column, or null",
  "group": "exact name of a column to group by, or null",
  "date": "exact name of a date column, or null",
  "order": "desc | asc",
  "n": "how many results to return, or null",
  "period": "day | month | year | null",
  "reason": "only when op is unknown: one friendly sentence saying why"
}

What each op does:
- aggregate: one number (no group) or a ranked comparison (with group).
  "total revenue" -> agg sum, value Revenue.
  "which region has the highest sales" -> agg sum, group Region, order desc, n 1.
  "top 5 products" -> group Product, order desc, n 5.
- count_unique: how many different values a column has. Put the column in group.
- trend: change over time. Needs a date column.
- outliers: unusual values. Leave value null to check every numeric column.
- missing: empty cells per column.
- correlation: relationships between numeric columns. If the question names two, put them in value and value2.
- distribution: breakdown of one column. Put it in group (category) or value (number).
- head: show the first n rows.
- insights: a general summary. n is how many insights.

Rules:
- Copy column names exactly as given. People use other words for them
  ("sales" may mean a column called Revenue), so match by meaning.
- If the question cannot be answered from these columns, use op "unknown"
  and explain in "reason" which information is missing.
"""


def build_user_prompt(schema, question):
    lines = [f"- {c['name']} ({c['kind']})" for c in schema["column_details"]]
    return "Columns:\n" + "\n".join(lines) + f"\n\nQuestion: {question}"
