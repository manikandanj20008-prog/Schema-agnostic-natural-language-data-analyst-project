"""Quick check that the analysis engine works on this computer."""
import sys
from pathlib import Path
try:
    from analyzer import load_table, detect_schema, auto_insights, run_plan
    from planner import rule_plan
    raw = (Path(__file__).parent / "sample_data" / "sales.csv").read_bytes()
    df = load_table("sales.csv", raw)
    schema = detect_schema(df, "sales.csv")
    auto_insights(df, schema)
    run_plan(df, schema, rule_plan("total revenue", schema))
    print("Self-test: OK")
except Exception as e:
    import traceback; traceback.print_exc()
    print("\nSELF-TEST FAILED. Screenshot this window and send it to Claude.")
    sys.exit(1)
