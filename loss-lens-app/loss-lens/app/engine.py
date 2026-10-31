"""
Question answering engine: question -> SQL -> validated -> result -> short answer.
Uses the AI when a provider is configured, otherwise matches a worked example.
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

import llm
from guard import GuardError, validate
from semantic import AREAS, EXAMPLES, system_prompt

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "out" / "loss_lens.duckdb"
LOG_PATH = ROOT / "logs" / "audit.jsonl"

SQL_START = re.compile(r"(?is)^\s*(select|with|delete|drop|update|insert|create|alter|attach|copy|pragma|install|load|set)\b")
STOP = set("the a an of in on for to and or is are was were which what how many much show me list give with by "
           "our we do does did have has this that last each per".split())


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=True)


def audit(entry: dict) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), **entry}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_audit(n: int = 200) -> pd.DataFrame:
    if not LOG_PATH.exists():
        return pd.DataFrame()
    rows = [json.loads(l) for l in LOG_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    return pd.DataFrame(rows[-n:][::-1])


# ---------------- offline matcher ----------------
def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1}


def match_example(question: str) -> tuple[str, str, float]:
    qt = _tokens(question)
    best, score = EXAMPLES[0], 0.0
    for q, s in EXAMPLES:
        et = _tokens(q)
        sc = len(qt & et) / max(1, len(qt | et))
        if sc > score:
            best, score = (q, s), sc
    q, s = best
    feeder = re.search(r"(?i)fdr-?\s?(\d{1,3})", question)
    s = s.replace("{feeder}", f"FDR-{int(feeder.group(1)):03d}" if feeder else "FDR-024")
    area = next((a for a in AREAS if a.lower() in question.lower()), "Chak 12")
    s = s.replace("{area}", area)
    return q, s, score


# ---------------- main entry ----------------
def answer(question: str) -> dict:
    """Return dict: mode, sql, df, error, summary, matched, attempts, ms."""
    t0 = time.time()
    out = {"question": question, "mode": None, "sql": None, "df": None,
           "error": None, "summary": None, "matched": None, "attempts": 0}

    # Direct SQL typed by the user: goes straight through the guardrails
    if SQL_START.match(question):
        out["mode"] = "direct SQL"
        out["sql"] = question.strip()
        _run(out)
        return _finish(out, t0)

    if llm.provider():
        out["mode"] = f"AI ({llm.provider()}: {llm.model_name()})"
        user = f"Question: {question}"
        for attempt in range(2):  # one self-correction retry
            out["attempts"] = attempt + 1
            try:
                out["sql"] = llm.extract_sql(llm.chat(system_prompt(), user))
            except Exception as e:
                out["error"] = str(e)
                return _finish(out, t0)
            _run(out)
            if not out["error"] or out.get("blocked"):
                break
            user = (f"Question: {question}\n\nYour previous SQL:\n{out['sql']}\n\n"
                    f"It failed with: {out['error']}\nReturn a corrected query.")
        if out["df"] is not None and not out["error"]:
            out["summary"] = _summarise(question, out["df"])
    else:
        out["mode"] = "offline (matched example)"
        q, s, score = match_example(question)
        out["matched"] = q
        out["match_score"] = round(score, 2)
        if score < 0.12:
            out["error"] = "offline-no-match"
            return _finish(out, t0)
        out["sql"] = s
        _run(out)
    return _finish(out, t0)


def _run(out: dict) -> None:
    out["error"], out["blocked"] = None, False
    try:
        safe = validate(out["sql"])
    except GuardError as e:
        out["error"], out["blocked"] = f"Blocked by guardrails: {e}", True
        return
    try:
        with connect() as con:
            out["df"] = con.execute(safe).df()
        out["sql"] = safe
    except Exception as e:
        out["error"] = f"Query error: {str(e).splitlines()[0]}"


def _summarise(question: str, df: pd.DataFrame) -> str | None:
    try:
        sample = df.head(15).to_csv(index=False)
        return llm.chat(
            "You explain query results to a utility manager in 2-3 plain sentences. "
            "Use the numbers given. Do not invent data. Mention the single most important finding first.",
            f"Question: {question}\nRows returned: {len(df)}\nFirst rows (CSV):\n{sample}",
            max_tokens=300).strip()
    except Exception:
        return None


def _finish(out: dict, t0: float) -> dict:
    out["ms"] = int((time.time() - t0) * 1000)
    audit({"question": out["question"], "mode": out["mode"], "sql": out["sql"],
           "status": "blocked" if out.get("blocked") else ("error" if out["error"] else "ok"),
           "rows": None if out["df"] is None else len(out["df"]),
           "detail": out["error"], "ms": out["ms"]})
    return out


def work_order(row: dict) -> str:
    """Field inspection work order. Bilingual (English + Urdu) when AI is on."""
    base = (f"WORK ORDER — Meter inspection\n"
            f"Customer: {row['customer_id']} ({row.get('customer_name', '')})\n"
            f"Feeder / transformer: {row['feeder_id']} / {row['transformer_id']}\n"
            f"Tariff: {row['tariff']}   Risk score: {row['risk_score']}\n"
            f"Why: {row['reasons']}\n"
            f"Usage: {row['avg_kwh_first30']} kWh/day (July) -> {row['avg_kwh_last30']} kWh/day (September)\n"
            f"Checks: meter seal and terminal cover; bypass wiring; magnets near meter; "
            f"phase/neutral reversal; photograph meter and connection; record findings.")
    if not llm.provider():
        return base
    try:
        return llm.chat(
            "Write a short field inspection work order for an electricity meter inspector. "
            "First in English (5-7 lines), then the same in Urdu script. Be practical and polite to the customer. "
            "Do not accuse the customer; say 'suspected' or 'to verify'.",
            base, max_tokens=700)
    except Exception:
        return base
