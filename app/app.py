"""
Loss Lens — AI copilot for finding electricity losses, theft and overbilling.
Run from the project folder:   streamlit run app/app.py
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

import engine  # noqa: E402
import llm  # noqa: E402
from guard import ATTACKS  # noqa: E402
from semantic import EXAMPLES  # noqa: E402

st.set_page_config(page_title="Loss Lens", page_icon="⚡", layout="wide")

ACCENT = "#C2410C"
AREA_COLORS = {"urban": "#2563EB", "rural": "#C2410C", "industrial": "#6B7280"}
px.defaults.template = "plotly_white"

if not engine.DB_PATH.exists():
    st.error(f"Database not found at {engine.DB_PATH}. Run:  python data/generate.py")
    st.stop()


@st.cache_data(show_spinner=False)
def q(sql: str) -> pd.DataFrame:
    with engine.connect() as con:
        return con.execute(sql).df()


def fmt_pkr(x: float) -> str:
    if x >= 1e9:
        return f"PKR {x/1e9:,.2f} bn"
    if x >= 1e6:
        return f"PKR {x/1e6:,.1f} M"
    return f"PKR {x:,.0f}"


def auto_chart(df: pd.DataFrame):
    """Pick a sensible chart for a query result, or None."""
    if df is None or df.empty or len(df.columns) < 2:
        return None
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not nums:
        return None
    time_col = next((c for c in df.columns if c in ("read_date", "month", "event_ts")), None)
    if time_col:
        ys = [c for c in nums if c != time_col][:3]
        return px.line(df, x=time_col, y=ys, markers=len(df) < 15)
    label = next((c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])), None)
    if label and len(df) <= 40:
        priority = ["excess", "refund", "diff_pkr", "suspects", "faulty", "risk", "collection", "loss_pct", "pkr", "pct"]
        y = next((c for key in priority for c in nums if key in c), nums[-1])
        fig = px.bar(df, x=label, y=y, color_discrete_sequence=[ACCENT])
        fig.update_layout(xaxis_title=None)
        return fig
    return None


# ---------------- sidebar ----------------
with st.sidebar:
    st.markdown("## ⚡ Loss Lens")
    st.caption("AI copilot that finds where electricity is lost or stolen — and who is unfairly overbilled.")
    p = llm.provider()
    if p:
        st.success(f"AI: {p} · {llm.model_name()}")
    else:
        st.info("AI: offline mode (no key in .env). Ask matches worked examples; all other screens work fully.")
    meta = q("SELECT (SELECT COUNT(*) FROM feeders) f, (SELECT COUNT(*) FROM customers) c, "
             "(SELECT MIN(read_date) FROM ami_daily_reads) d0, (SELECT MAX(read_date) FROM ami_daily_reads) d1").iloc[0]
    st.markdown(f"**Riverbend Power** (synthetic)  \n{meta.f} feeders · {meta.c:,} smart meters  \n"
                f"{meta.d0:%d %b} – {meta.d1:%d %b %Y}")
    st.caption("All data is synthetic. No real customer or utility data is used.")

tabs = st.tabs(["📊 Overview", "💬 Ask", "🔎 Inspection list", "⚖️ Fair billing", "🎯 Accuracy", "🧾 Audit log"])

# ---------------- Overview ----------------
with tabs[0]:
    st.markdown("### Where is our energy going?")
    fm = q("SELECT * FROM v_feeder_loss_monthly")
    rate = q("SELECT SUM(bill_amount_pkr)/SUM(billed_kwh) r, SUM(bill_amount_pkr) b FROM billing").iloc[0]
    excess_kwh = (fm.input_kwh * fm.excess_loss_pct.clip(lower=0) / 100).sum()
    total_in = fm.input_kwh.sum()
    avg_loss = 100 * (fm.input_kwh.sum() - fm.metered_kwh.sum()) / total_in
    suspects = q("SELECT COUNT(*) n FROM v_inspection_list WHERE risk_score >= 30").n[0]
    refund = q("SELECT COALESCE(SUM(diff_pkr),0) s, COUNT(DISTINCT customer_id) n FROM v_billing_mismatch WHERE diff_pct >= 30").iloc[0]
    bill_cut = 100 * excess_kwh * rate.r / rate.b

    c = st.columns(5)
    c[0].metric("Overall loss", f"{avg_loss:.1f}%", help="(input − metered) / input, all feeders, 3 months")
    c[1].metric("Loss above technical", f"{excess_kwh/1e3:,.0f} MWh", help="Energy lost beyond normal line/transformer losses")
    c[2].metric("Value of that energy", fmt_pkr(excess_kwh * rate.r))
    c[3].metric("Meters to inspect", f"{suspects}")
    c[4].metric("Overbilled customers", f"{int(refund.n)}", help=f"Refund due {fmt_pkr(refund.s)}")
    st.info(f"**Why it matters:** losses are recovered through tariffs, so honest customers pay for them. "
            f"Recovering the excess loss here is worth about **{bill_cut:.1f}% of all bills** — money that "
            f"could come off honest customers' tariffs.")

    feeder = (fm.groupby(["feeder_id", "feeder_name", "area", "area_type"], as_index=False)
              .agg(loss_pct=("loss_pct", "mean"), excess_loss_pct=("excess_loss_pct", "mean"),
                   collection_pct=("collection_pct", "mean"))
              .sort_values("excess_loss_pct", ascending=False))
    left, right = st.columns([3, 2])
    with left:
        fig = px.bar(feeder, x="feeder_id", y="excess_loss_pct", color="area_type",
                     color_discrete_map=AREA_COLORS, hover_data=["feeder_name", "loss_pct", "collection_pct"],
                     labels={"excess_loss_pct": "Loss above technical (%)", "feeder_id": "", "area_type": "Area"})
        fig.update_layout(title="Feeders ranked by loss above technical losses", height=380,
                          legend=dict(orientation="h", y=1.08))
        st.plotly_chart(fig, width="stretch")
    with right:
        sel = st.selectbox("Drill into a feeder", feeder.feeder_id,
                           format_func=lambda f: f"{f} · {feeder.set_index('feeder_id').loc[f, 'feeder_name']}")
        d = q(f"SELECT * FROM v_feeder_loss_daily WHERE feeder_id = '{sel}' ORDER BY read_date")
        fig = px.line(d, x="read_date", y=["input_kwh", "metered_kwh"],
                      color_discrete_sequence=["#111827", ACCENT],
                      labels={"value": "kWh per day", "read_date": "", "variable": ""})
        fig.update_layout(title=f"{sel}: energy sent in vs energy metered", height=330,
                          legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, width="stretch")
        st.caption("The gap between the lines is lost energy. A wide gap means theft or hooks (kunda).")
    st.dataframe(feeder.round(1), hide_index=True, width="stretch")

# ---------------- Ask ----------------
with tabs[1]:
    st.markdown("### Ask Loss Lens")
    st.caption("Ask in plain English. You'll see the answer, the SQL behind it, and a chart. "
               "Every query is checked by guardrails and written to the audit log.")
    if "ask_q" not in st.session_state:
        st.session_state.ask_q = ""

    def _use_pill():
        if st.session_state.get("pill"):
            st.session_state.ask_q = st.session_state.pill

    def _run_attack(sql: str):
        st.session_state.ask_q = sql
        st.session_state.last = engine.answer(sql)

    ex_qs = [e[0] for e in EXAMPLES[:8]]
    st.pills("Try one:", ex_qs, selection_mode="single", key="pill", on_change=_use_pill)
    question = st.text_input("Your question", key="ask_q",
                             placeholder="e.g. Which feeders in Chak 12 lose the most energy?")
    go = st.button("Ask", type="primary")

    if go and question.strip():
        with st.spinner("Thinking…"):
            st.session_state.last = engine.answer(question.strip())

    res = st.session_state.get("last")
    if res:
        st.caption(f"Mode: {res['mode']} · {res['ms']} ms" +
                   (f" · self-corrected ({res['attempts']} attempts)" if res.get("attempts", 0) > 1 else ""))
        if res["error"] == "offline-no-match":
            st.warning("Offline mode can only answer questions similar to the worked examples. "
                       "Add an AI key in .env to ask anything. Try one of the suggestions above.")
        elif res.get("blocked"):
            st.error(f"🛡️ {res['error']}")
            st.code(res["sql"], language="sql")
        elif res["error"]:
            st.error(res["error"])
            if res["sql"]:
                st.code(res["sql"], language="sql")
        else:
            if res.get("matched"):
                st.caption(f"Matched worked example: “{res['matched']}”")
            if res.get("summary"):
                st.success(res["summary"])
            df = res["df"]
            fig = auto_chart(df)
            if fig is not None:
                fig.update_layout(height=360)
                st.plotly_chart(fig, width="stretch")
            st.dataframe(df, hide_index=True, width="stretch")
            st.caption(f"{len(df)} rows")
            with st.expander("SQL behind this answer"):
                st.code(res["sql"], language="sql")

    with st.expander("🛡️ Try to break it — guardrail test"):
        st.caption("These attacks go through exactly the same checks as AI-written SQL.")
        cols = st.columns(4)
        for i, (name, sql) in enumerate(ATTACKS):
            cols[i % 4].button(name, key=f"atk{i}", width="stretch", on_click=_run_attack, args=(sql,))

# ---------------- Inspection list ----------------
with tabs[2]:
    st.markdown("### Who should field crews visit first?")
    il = q("SELECT i.*, f.area FROM v_inspection_list i JOIN feeders f USING (feeder_id) ORDER BY risk_score DESC")
    c1, c2, c3 = st.columns([1, 2, 1])
    th = c1.slider("Minimum risk score", 0, 100, 30, 5)
    areas = c2.multiselect("Area", sorted(il.area.unique()))
    view = il[il.risk_score >= th]
    if areas:
        view = view[view.area.isin(areas)]
    c3.metric("Meters to inspect", len(view))

    cols = ["customer_id", "area", "feeder_id", "tariff", "risk_score", "reasons",
            "avg_kwh_first30", "avg_kwh_last30", "change_pct"]
    st.dataframe(view[cols], hide_index=True, width="stretch", height=320,
                 column_config={"risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=150,
                                                                             format="%d"),
                                "avg_kwh_first30": "kWh/day Jul", "avg_kwh_last30": "kWh/day Sep",
                                "change_pct": st.column_config.NumberColumn("Change %", format="%.0f%%")})
    st.download_button("⬇️ Download field work list (CSV)", view[cols].to_csv(index=False),
                       "loss_lens_inspection_list.csv", "text/csv")

    if len(view):
        st.markdown("#### Inspect one customer")
        cid = st.selectbox("Customer", view.customer_id.head(200))
        row = view.set_index("customer_id").loc[cid]
        reads = q(f"SELECT read_date, kwh FROM ami_daily_reads WHERE customer_id = '{cid}' ORDER BY read_date")
        ev = q(f"SELECT event_ts, event_type FROM meter_events WHERE customer_id = '{cid}' ORDER BY event_ts")
        a, b = st.columns([3, 2])
        with a:
            fig = px.line(reads, x="read_date", y="kwh", color_discrete_sequence=["#111827"],
                          labels={"kwh": "kWh per day", "read_date": ""})
            for e in ev.itertuples():
                fig.add_vline(x=e.event_ts, line_dash="dot", line_color=ACCENT)
                fig.add_annotation(x=e.event_ts, y=reads.kwh.max(), text=e.event_type.replace("_", " ").title(),
                                   showarrow=False, textangle=-90, font=dict(size=10, color=ACCENT), xanchor="right")
            fig.update_layout(title=f"{cid}: daily consumption with meter events", height=330)
            st.plotly_chart(fig, width="stretch")
        with b:
            st.markdown(f"**Risk score:** {row.risk_score}  \n**Why:** {row.reasons}")
            if st.button("📝 Generate field work order", key="wo_btn"):
                with st.spinner("Writing work order…"):
                    st.session_state.wo_text = engine.work_order({"customer_id": cid, **row.to_dict()})
                    st.session_state.wo_for = cid
            if st.session_state.get("wo_text") and st.session_state.get("wo_for") == cid:
                st.text_area("Work order", st.session_state.wo_text, height=260, key=f"wo_area_{cid}")

# ---------------- Fair billing ----------------
with tabs[3]:
    st.markdown("### Who is being overbilled?")
    st.caption("Affordability works both ways: catching theft protects honest customers, "
               "and catching overbilling protects the poorest ones.")
    mm = q("SELECT * FROM v_billing_mismatch WHERE diff_pct >= 30 ORDER BY diff_pkr DESC")
    c = st.columns(3)
    c[0].metric("Customers overbilled", mm.customer_id.nunique())
    c[1].metric("Extra kWh billed", f"{mm.diff_kwh.sum():,.0f}")
    c[2].metric("Refund due", fmt_pkr(mm.diff_pkr.sum()))
    by = mm.groupby("feeder_id", as_index=False).diff_pkr.sum().sort_values("diff_pkr", ascending=False)
    fig = px.bar(by, x="feeder_id", y="diff_pkr", color_discrete_sequence=[ACCENT],
                 labels={"diff_pkr": "Refund due (PKR)", "feeder_id": ""})
    fig.update_layout(title="Refund due by feeder", height=320)
    st.plotly_chart(fig, width="stretch")
    st.dataframe(mm, hide_index=True, width="stretch",
                 column_config={"diff_pct": st.column_config.NumberColumn("Over-billed %", format="%.0f%%"),
                                "diff_pkr": st.column_config.NumberColumn("Refund PKR", format="%,.0f")})
    st.caption("Pattern found: these are ESTIMATED bills far above what the smart meter actually recorded.")

# ---------------- Accuracy ----------------
with tabs[4]:
    st.markdown("### How good is it? Tested against the answer key")
    gt_path = engine.ROOT / "data" / "out" / "ground_truth.csv"
    if not gt_path.exists():
        st.warning("ground_truth.csv not found in data/out.")
    else:
        gt = pd.read_csv(gt_path)
        st.caption("The synthetic dataset has known, planted problems. The answer key is never shown to the AI "
                   "or used by the rules — it is only used here to score results.")
        th2 = st.slider("Risk-score threshold", 0, 100, 30, 5, key="th2")
        il_all = q("SELECT customer_id, risk_score FROM v_inspection_list")
        flagged = set(il_all[il_all.risk_score >= th2].customer_id)
        cust = gt.dropna(subset=["customer_id"])
        target = cust[~cust.anomaly_type.isin(["OVERBILLING"])]
        tset = set(target.customer_id)
        tp = len(flagged & tset)
        prec = tp / len(flagged) if flagged else 0
        rec = tp / len(tset) if tset else 0
        hook = set(gt[gt.anomaly_type == "HOOK_THEFT_FEEDER"].feeder_id)
        top_feeders = set(feeder.head(len(hook)).feeder_id)
        ob = set(cust[cust.anomaly_type == "OVERBILLING"].customer_id)
        ob_found = set(mm.customer_id)
        c = st.columns(4)
        c[0].metric("Precision", f"{prec:.0%}", help="Of meters flagged, share that truly had a problem")
        c[1].metric("Recall", f"{rec:.0%}", help="Of meters with a problem, share that was flagged")
        c[2].metric("Hook-theft feeders found", f"{len(top_feeders & hook)}/{len(hook)}")
        c[3].metric("Overbilling found", f"{len(ob_found & ob)}/{len(ob)}")
        per = (target.assign(found=target.customer_id.isin(flagged))
               .groupby("anomaly_type").agg(planted=("customer_id", "count"), found=("found", "sum")))
        per["recall"] = (100 * per.found / per.planted).round(0).astype(int).astype(str) + "%"
        st.dataframe(per.reset_index(), hide_index=True, width="stretch")
        st.caption("Honest note: rules score this well because the data is synthetic. Real smart-meter data is "
                   "noisier — which is why Loss Lens shows its reasons and SQL, and a human approves every inspection.")

# ---------------- Audit ----------------
with tabs[5]:
    st.markdown("### Audit log")
    st.caption("Every question, the SQL that ran (or was blocked), and the outcome.")
    log = engine.read_audit()
    if log.empty:
        st.write("No questions asked yet.")
    else:
        st.dataframe(log, hide_index=True, width="stretch")
