"""
SQL guardrails for Loss Lens.

Every query, whether written by the AI or typed by a user, passes through
validate() before it touches the database. A query is allowed only if it is:
  - exactly one statement
  - a read-only SELECT (or WITH ... SELECT)
  - using known tables/views only
  - free of file, network and system functions
A row limit is added if missing. The database itself is also opened read-only,
so this is defence in depth.
"""
import re

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {
    # semantic views (preferred)
    "v_feeder_loss_monthly", "v_feeder_loss_daily", "v_customer_consumption",
    "v_meter_tamper_events", "v_billing_mismatch", "v_inspection_list",
    # base tables (read-only)
    "feeders", "transformers", "customers", "ami_daily_reads",
    "meter_events", "feeder_input", "billing",
}

BLOCKED_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto",
    "read_text", "read_blob", "glob", "parquet_scan", "csv_scan", "json_scan",
    "sniff_csv", "httpfs", "getenv", "current_setting", "duckdb_secrets",
    "duckdb_settings", "duckdb_extensions", "load", "install", "query", "query_table",
}

MAX_ROWS = 500


class GuardError(Exception):
    """Raised when a query is blocked. The message is shown to the user."""


def validate(sql: str) -> str:
    """Return a safe, row-limited SQL string, or raise GuardError."""
    if not sql or not sql.strip():
        raise GuardError("Empty query.")
    text = sql.strip().rstrip(";").strip()

    try:
        statements = [s for s in sqlglot.parse(text, read="duckdb") if s is not None]
    except Exception as e:  # unparseable
        raise GuardError(f"Could not parse SQL: {str(e).splitlines()[0]}")

    if len(statements) != 1:
        raise GuardError("Only one statement is allowed.")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise GuardError(f"Only read-only SELECT queries are allowed (got {tree.key.upper()}).")

    for bad in (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
                exp.Command, exp.Copy, exp.Attach, exp.Detach, exp.Pragma, exp.Set, exp.Use):
        if tree.find(bad):
            raise GuardError(f"Blocked operation: {bad.__name__.upper()}.")

    # Tables: every real table reference must be allow-listed (CTE names are fine)
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if isinstance(t.this, exp.Anonymous) or t.find(exp.Anonymous):
            fname = (t.this.name if isinstance(t.this, exp.Anonymous) else "function").lower()
            raise GuardError(f"Table functions are not allowed ({fname}).")
        name = t.name.lower()
        if not name:
            raise GuardError("Table functions (file or system access) are not allowed.")
        if t.args.get("db") or t.args.get("catalog"):
            raise GuardError(f"Schema-qualified tables are not allowed ({t.sql()}).")
        if name not in ALLOWED_TABLES and name not in cte_names:
            raise GuardError(f"Unknown or disallowed table: {name}.")

    # Functions: block file/network/system access anywhere in the query
    for f in tree.find_all(exp.Func):
        fname = (f.name if isinstance(f, exp.Anonymous) else f.sql_name()).lower()
        if fname in BLOCKED_FUNCTIONS:
            raise GuardError(f"Blocked function: {fname}.")
    if re.search(r"(?i)\b(read_\w+|glob|getenv|httpfs)\s*\(", text):
        raise GuardError("Blocked file or system function.")

    # Row limit
    if isinstance(tree, exp.Select) and not tree.args.get("limit"):
        tree = tree.limit(MAX_ROWS)
        return tree.sql(dialect="duckdb")
    if not isinstance(tree, exp.Select):
        return f"SELECT * FROM ({tree.sql(dialect='duckdb')}) AS q LIMIT {MAX_ROWS}"
    return tree.sql(dialect="duckdb")


ATTACKS = [
    ("Delete billing records", "DELETE FROM billing"),
    ("Drop a table", "DROP TABLE customers"),
    ("Two statements (injection)", "SELECT * FROM feeders; DROP TABLE billing"),
    ("Read a file from disk", "SELECT * FROM read_csv('C:/Users/secrets.csv')"),
    ("Change the answer key", "UPDATE billing SET billed_kwh = 0"),
    ("Read environment secrets", "SELECT getenv('ANTHROPIC_API_KEY')"),
    ("Attach another database", "ATTACH 'other.db' AS x"),
    ("Hidden table function", "SELECT * FROM glob('*')"),
]
