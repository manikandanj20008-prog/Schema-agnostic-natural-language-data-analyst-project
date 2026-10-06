"""
planner.py — turns a plain-English question into an analysis plan.

Two engines produce the same kind of plan:
  1. Rules  — keyword matching. Free, instant, works with no internet.
  2. Claude — used automatically when ANTHROPIC_API_KEY is set. Understands
              looser wording. If the call fails, the rules engine takes over.
"""
import json
import os
import re

from prompts import PLAN_SYSTEM_PROMPT, build_user_prompt

CLAUDE_MODEL = "claude-opus-5-5"

# Words people use interchangeably. Used to match a question to a column
# even when the exact column name is not typed.
SYNONYMS = [
    {"revenue", "sale", "income", "earning", "turnover"},
    {"cost", "price", "expense", "spend", "charge", "fee", "bill", "amount", "payment"},
    {"quantity", "qty", "unit", "volume"},
    {"mark", "score", "grade", "point", "result"},
    {"department", "dept", "division", "ward", "unit"},
    {"region", "area", "zone", "location", "city", "state"},
    {"product", "item", "sku"},
    {"customer", "client", "buyer"},
    {"patient", "person", "people"},
    {"student", "pupil", "learner"},
    {"doctor", "physician"},
    {"category", "type", "kind", "class"},
    {"age", "old", "oldest", "older", "young", "youngest", "younger"},
    {"salary", "pay", "wage"},
]


def _tokens(text):
    words = re.sub(r"[^a-z0-9]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower()).split()
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]


def _score(column, q_tokens):
    """How strongly a question refers to a column (0 = not at all)."""
    col_tokens = _tokens(column)
    if not col_tokens:
        return 0
    if all(t in q_tokens for t in col_tokens):
        return len(col_tokens) + 1
    score = 0.5 * sum(1 for t in col_tokens if len(t) >= 3 and t in q_tokens)
    for group in SYNONYMS:
        if group & set(col_tokens) and group & q_tokens:
            score = max(score, 0.8)
    return score


def _best(columns, q_tokens, focus=()):
    """The best-matching column. Columns named right after "which / by / per /
    each" win ties, then columns listed earlier in `columns`."""
    best, best_score = None, 0
    for c in columns:
        score = _score(c, q_tokens)
        if score and set(_tokens(c)) & set(focus):
            score += 2
        if score > best_score:
            best, best_score = c, score
    return best


def rule_plan(question, schema):
    q = question.lower()
    q_tokens = set(_tokens(question))

    def has(pattern):
        return re.search(pattern, q) is not None

    numeric = schema["numeric_columns"]
    # Category columns first, so they win ties against free-text columns.
    others = schema["categorical_columns"] + [
        c for c in schema["columns"]
        if c not in numeric and c not in schema["date_columns"] and c not in schema["categorical_columns"]
    ]
    focus = _tokens(" ".join(re.findall(r"\b(?:which|by|per|each|every)\s+(\w+)", q)))
    value = _best(numeric, q_tokens)
    group = _best(others, q_tokens, focus)
    number = re.search(r"\b(\d{1,2})\b", q)
    n = int(number.group(1)) if number else None
    plan = {"value": value, "group": group, "date": None, "n": n}
    mentioned = sorted((c for c in numeric if _score(c, q_tokens) > 0), key=lambda c: -_score(c, q_tokens))

    if has(r"insight|summar|overview|describe|tell me about"):
        return dict(plan, op="insights")
    if has(r"outlier|unusual|anomal|abnormal|strange|weird"):
        return dict(plan, op="outliers")
    if has(r"missing|null|empty|blank|incomplete"):
        return dict(plan, op="missing")
    if has(r"correlat|relationship|related"):
        pair = mentioned[:2] if len(mentioned) >= 2 else [None, None]
        return dict(plan, op="correlation", value=pair[0], value2=pair[1])

    agg = ("mean" if has(r"\baverage|\bavg\b|\bmean\b") else
           "median" if has(r"\bmedian") else
           "count" if has(r"how many|\bcount|number of") else
           "sum" if has(r"\btotal|\bsum\b|overall") else None)

    if has(r"trend|over time|monthly|per month|by month|each month|yearly|per year|by year|daily|per day|growth"):
        period = "year" if has(r"year|annual") else "day" if has(r"dai|per day") else "month" if has(r"month") else None
        return dict(plan, op="trend", agg=agg, period=period, group=None)
    if has(r"(first|top|last)\s*\d*\s*rows?\b|\b(show|display|give|list|see)\b.{0,20}\brows?\b|show (me )?(the )?(data|table)|preview|sample rows|\bhead\b"):
        return dict(plan, op="head")
    if has(r"distribution|breakdown|spread|histogram|share of"):
        return dict(plan, op="distribution")

    low = has(r"lowest|least|bottom|worst|smallest|minimum|\bmin\b|fewest|cheapest|youngest|shortest")
    high = has(r"highest|most|\btop\b|best|largest|biggest|maximum|\bmax\b|greatest|oldest|longest")
    order = "asc" if low and not high else "desc"
    ranked = low or high or has(r"\bby\b|\bper\b|\beach\b|compare")

    if group:
        if agg == "count" and not ranked:
            return dict(plan, op="count_unique")
        if n is None and (low or high) and not has(r"\btop\b|\bbottom\b"):
            plan["n"] = 1
        return dict(plan, op="aggregate", agg=agg, order=order)

    if agg is None and (low or high):
        agg = "min" if order == "asc" else "max"
    if agg is None:
        return {"op": "unknown"}
    if agg != "count" and value is None and len(schema["measure_columns"]) > 1:
        names = ", ".join(schema["measure_columns"])
        return {"op": "unknown", "reason": f"Which number do you mean? This dataset has: {names}."}
    return dict(plan, op="aggregate", agg=agg, order=order, group=None)


def claude_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def claude_plan(question, schema):
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=PLAN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(schema, question)}],
    )
    if response.stop_reason == "refusal":
        raise ValueError("Claude declined the request")
    text = "".join(block.text for block in response.content if block.type == "text")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("Claude did not return a plan")
    return json.loads(match.group(0))


def make_plan(question, schema):
    """Returns (plan, engine_name, note). note explains a fallback, if any."""
    if not claude_available():
        return rule_plan(question, schema), "rules", None

    import anthropic
    try:
        return claude_plan(question, schema), "claude", None
    except anthropic.AuthenticationError:
        note = "The Claude API key was rejected, so the built-in rules answered instead."
    except anthropic.RateLimitError:
        note = "Claude is rate limited right now, so the built-in rules answered instead."
    except anthropic.APIError:
        note = "Claude could not be reached, so the built-in rules answered instead."
    except ValueError:
        note = "Claude's reply could not be read, so the built-in rules answered instead."
    return rule_plan(question, schema), "rules", note
