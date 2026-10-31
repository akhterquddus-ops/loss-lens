"""
Loss Lens — synthetic utility dataset generator.

Builds a fictional distribution company ("Riverbend Power") with feeders,
transformers, customers, 90 days of smart-meter (AMI) reads, meter events and
monthly billing. Realistic loss and theft patterns are planted, and the answer
key is written to ground_truth.csv so detection accuracy can be measured.

All data is synthetic. No real customer, utility or meter data is used.

Usage:
    python generate.py                 # default size, seed 42
    python generate.py --customers 3000 --seed 7
"""
import argparse
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

AREAS = [
    # name, type
    ("Model Town", "urban"), ("Satellite Town", "urban"), ("Gulberg", "urban"),
    ("Old City", "urban"), ("Canal View", "urban"), ("Industrial Estate", "industrial"),
    ("Green Valley", "rural"), ("Chak 12", "rural"), ("Mandi Road", "rural"),
    ("River Side", "rural"),
]
SUBSTATIONS = ["North Grid", "City Grid", "East Grid", "South Grid"]

TARIFFS = {
    # tariff: (share, mean daily kWh, sd, sanctioned kW range)
    "Residential": (0.80, 9.0, 4.0, (1, 5)),
    "Commercial":  (0.13, 28.0, 12.0, (3, 15)),
    "Industrial":  (0.03, 220.0, 90.0, (25, 150)),
    "Agricultural": (0.04, 45.0, 20.0, (5, 25)),
}
RATE_PER_KWH = {"Residential": 52.0, "Commercial": 68.0, "Industrial": 58.0, "Agricultural": 38.0}  # PKR, illustrative


def main(n_customers: int, days: int, seed: int, out: str) -> None:
    rng = np.random.default_rng(seed)
    os.makedirs(out, exist_ok=True)
    start = date(2026, 7, 1)
    dates = pd.date_range(start, periods=days, freq="D")

    # ---------------- Feeders ----------------
    feeders = []
    fid = 1
    for area, atype in AREAS:
        for _ in range(3):
            feeders.append({
                "feeder_id": f"FDR-{fid:03d}",
                "feeder_name": f"{area} {fid}",
                "substation": SUBSTATIONS[(fid - 1) % len(SUBSTATIONS)],
                "area": area,
                "area_type": atype,
                "voltage_kv": 11,
            })
            fid += 1
    feeders = pd.DataFrame(feeders)

    # Feeders with heavy hook (kunda) theft: mostly rural/old-city
    hook_candidates = feeders[feeders.area.isin(["Old City", "Chak 12", "Mandi Road", "River Side"])].feeder_id.tolist()
    hook_feeders = list(rng.choice(hook_candidates, size=5, replace=False))
    # Technical loss baseline per feeder (line + transformer losses)
    feeders["tech_loss_pct"] = np.where(feeders.area_type == "rural",
                                        rng.uniform(9, 12, len(feeders)),
                                        rng.uniform(5.5, 8, len(feeders))).round(2)

    # ---------------- Transformers ----------------
    transformers = []
    tid = 1
    for f in feeders.itertuples():
        for _ in range(rng.integers(8, 13)):
            transformers.append({
                "transformer_id": f"TX-{tid:04d}",
                "feeder_id": f.feeder_id,
                "kva_rating": int(rng.choice([25, 50, 100, 200])),
            })
            tid += 1
    transformers = pd.DataFrame(transformers)

    # ---------------- Customers ----------------
    tariff_names = list(TARIFFS)
    tariff_p = [TARIFFS[t][0] for t in tariff_names]
    tx_choice = rng.choice(transformers.transformer_id, size=n_customers)
    tx_to_feeder = dict(zip(transformers.transformer_id, transformers.feeder_id))
    feeder_type = dict(zip(feeders.feeder_id, feeders.area_type))

    cust = pd.DataFrame({
        "customer_id": [f"CUST-{i:06d}" for i in range(1, n_customers + 1)],
        "transformer_id": tx_choice,
    })
    cust["feeder_id"] = cust.transformer_id.map(tx_to_feeder)
    # tariff mix depends on area type
    tariffs = []
    for ft in cust.feeder_id.map(feeder_type):
        p = np.array(tariff_p)
        if ft == "industrial":
            p = np.array([0.35, 0.25, 0.38, 0.02])
        elif ft == "rural":
            p = np.array([0.78, 0.07, 0.01, 0.14])
        tariffs.append(rng.choice(tariff_names, p=p / p.sum()))
    cust["tariff"] = tariffs
    cust["meter_id"] = [f"MTR-{i:07d}" for i in rng.choice(9_000_000, n_customers, replace=False) + 1_000_000]
    cust["meter_type"] = "AMI"
    cust["connection_date"] = [
        (date(2005, 1, 1) + timedelta(days=int(d))).isoformat()
        for d in rng.integers(0, 7000, n_customers)
    ]
    cust["customer_name"] = [f"Customer {i}" for i in range(1, n_customers + 1)]

    # ---------------- True consumption ----------------
    base = np.array([
        max(0.5, rng.normal(TARIFFS[t][1], TARIFFS[t][2])) for t in cust.tariff
    ])
    # Sanctioned load tracks typical usage: honest load factor ~10-22%
    lo = np.array([TARIFFS[t][3][0] for t in cust.tariff])
    cust["sanctioned_load_kw"] = np.maximum(
        lo, np.ceil(base / 24.0 / rng.uniform(0.10, 0.22, n_customers))
    ).astype(int)
    doy = np.arange(days)
    # Summer -> early autumn: cooling load declines over the window
    seasonal = 1.15 - 0.30 * (doy / days)
    weekly = np.where(pd.Series(dates).dt.dayofweek.values == 6, 0.9, 1.0)  # Sunday dip
    noise = rng.normal(1.0, 0.12, (n_customers, days)).clip(0.4, 1.8)
    true_kwh = (base[:, None] * seasonal[None, :] * weekly[None, :] * noise).round(2)

    metered = true_kwh.copy()
    truth = []  # ground truth rows
    events = []  # meter events

    def add_event(i, day_idx, etype):
        ts = pd.Timestamp(dates[day_idx]) + pd.Timedelta(minutes=int(rng.integers(0, 1440)))
        events.append({"meter_id": cust.meter_id[i], "customer_id": cust.customer_id[i],
                       "event_ts": ts, "event_type": etype})

    idx_all = np.arange(n_customers)
    used = set()

    def pick(n, mask=None):
        pool = idx_all if mask is None else idx_all[mask]
        pool = np.array([p for p in pool if p not in used])
        chosen = rng.choice(pool, size=min(n, len(pool)), replace=False)
        used.update(chosen.tolist())
        return chosen

    # 1) Meter bypass: sudden 55–85% drop from a date, tamper event near it
    for i in pick(int(n_customers * 0.020)):
        d0 = int(rng.integers(20, days - 20))
        keep = rng.uniform(0.15, 0.45)
        metered[i, d0:] = (metered[i, d0:] * keep).round(2)
        add_event(i, max(0, d0 - int(rng.integers(0, 3))), rng.choice(["COVER_OPEN", "TERMINAL_COVER_OPEN"]))
        truth.append({"customer_id": cust.customer_id[i], "anomaly_type": "METER_BYPASS",
                      "start_date": dates[d0].date().isoformat(),
                      "est_unbilled_kwh": round(float((true_kwh[i, d0:] - metered[i, d0:]).sum()), 1)})

    # 2) Magnet tampering: intermittent low reads with magnetic events
    for i in pick(int(n_customers * 0.010)):
        tamper_days = rng.choice(days, size=int(days * 0.35), replace=False)
        metered[i, tamper_days] = (metered[i, tamper_days] * rng.uniform(0.05, 0.3)).round(2)
        for d in rng.choice(tamper_days, size=min(8, len(tamper_days)), replace=False):
            add_event(i, int(d), "MAGNETIC_INTERFERENCE")
        truth.append({"customer_id": cust.customer_id[i], "anomaly_type": "MAGNET_TAMPER",
                      "start_date": dates[int(tamper_days.min())].date().isoformat(),
                      "est_unbilled_kwh": round(float((true_kwh[i] - metered[i]).sum()), 1)})

    # 3) Reverse connection: negative/odd readings flagged as reverse energy
    for i in pick(int(n_customers * 0.004)):
        d0 = int(rng.integers(10, days - 10))
        metered[i, d0:] = (metered[i, d0:] * rng.uniform(0.0, 0.1)).round(2)
        for k in range(3):
            add_event(i, min(days - 1, d0 + k * 5), "REVERSE_ENERGY")
        truth.append({"customer_id": cust.customer_id[i], "anomaly_type": "REVERSE_CONNECTION",
                      "start_date": dates[d0].date().isoformat(),
                      "est_unbilled_kwh": round(float((true_kwh[i, d0:] - metered[i, d0:]).sum()), 1)})

    # 4) Stuck / faulty meter: flat identical reading (not theft — needs replacement)
    for i in pick(int(n_customers * 0.006)):
        d0 = int(rng.integers(15, days - 15))
        metered[i, d0:] = 0.0
        truth.append({"customer_id": cust.customer_id[i], "anomaly_type": "FAULTY_METER_ZERO",
                      "start_date": dates[d0].date().isoformat(),
                      "est_unbilled_kwh": round(float(true_kwh[i, d0:].sum()), 1)})

    # 5) Tariff misuse: commercial load on residential connection
    res_mask = (cust.tariff == "Residential").values
    for i in pick(int(n_customers * 0.008), res_mask):
        # running a shop / workshop on a house connection: commercial-scale usage
        target = rng.uniform(35, 70)
        true_kwh[i] = (true_kwh[i] / max(base[i], 0.5) * target).round(2)
        metered[i] = true_kwh[i]  # metered correctly, but wrong tariff
        truth.append({"customer_id": cust.customer_id[i], "anomaly_type": "TARIFF_MISUSE",
                      "start_date": dates[0].date().isoformat(), "est_unbilled_kwh": 0.0})

    # Noise events for honest customers (false-alarm material)
    for i in rng.choice(idx_all, size=int(n_customers * 0.05), replace=False):
        add_event(i, int(rng.integers(0, days)), rng.choice(["POWER_OUTAGE", "POWER_RESTORED", "LOW_VOLTAGE"]))
    for i in rng.choice(idx_all, size=int(n_customers * 0.004), replace=False):
        add_event(i, int(rng.integers(0, days)), "COVER_OPEN")  # e.g. legitimate maintenance

    # ---------------- AMI daily reads ----------------
    reads = pd.DataFrame({
        "meter_id": np.repeat(cust.meter_id.values, days),
        "customer_id": np.repeat(cust.customer_id.values, days),
        "read_date": np.tile(dates.date, n_customers),
        "kwh": metered.reshape(-1),
    })
    # Communication gaps: ~1.5% missing reads
    reads = reads.sample(frac=0.985, random_state=seed).sort_values(["customer_id", "read_date"])

    # ---------------- Feeder input energy ----------------
    true_df = pd.DataFrame(true_kwh, columns=dates.date)
    true_df["feeder_id"] = cust.feeder_id.values
    feeder_true = true_df.groupby("feeder_id").sum()  # true customer consumption per feeder-day
    tech = feeders.set_index("feeder_id").tech_loss_pct / 100.0
    hook_extra = pd.Series(0.0, index=feeders.feeder_id)
    for f in hook_feeders:
        hook_extra[f] = rng.uniform(0.18, 0.30)  # unmetered hook load as share of consumption
    feeder_rows = []
    for f in feeder_true.index:
        series = feeder_true.loc[f].values
        hook = series * hook_extra[f] * rng.normal(1, 0.05, days)
        inp = (series + hook) / (1 - tech[f])
        for d, v in zip(dates.date, inp):
            feeder_rows.append({"feeder_id": f, "read_date": d, "input_kwh": round(float(v), 1)})
    feeder_input = pd.DataFrame(feeder_rows)
    for f in hook_feeders:
        truth.append({"customer_id": None, "anomaly_type": "HOOK_THEFT_FEEDER", "feeder_id": f,
                      "start_date": dates[0].date().isoformat(),
                      "est_unbilled_kwh": round(float((feeder_true.loc[f].values * hook_extra[f]).sum()), 1)})

    # ---------------- Billing (monthly) ----------------
    reads["month"] = pd.to_datetime(reads.read_date).dt.to_period("M").astype(str)
    monthly = reads.groupby(["customer_id", "month"], as_index=False).kwh.sum()
    monthly = monthly.merge(cust[["customer_id", "tariff"]], on="customer_id")
    monthly["metered_kwh"] = monthly.kwh.round(1)
    monthly["billed_kwh"] = monthly.metered_kwh
    monthly["bill_basis"] = "ACTUAL"

    # 6) Overbilling: billed well above metered (affordability harm)
    over_ids = cust.customer_id.values[pick(int(n_customers * 0.012), res_mask)]
    for cid in over_ids:
        m = rng.choice(monthly.month.unique())
        sel = (monthly.customer_id == cid) & (monthly.month == m)
        factor = rng.uniform(1.6, 3.0)
        monthly.loc[sel, "billed_kwh"] = (monthly.loc[sel, "metered_kwh"] * factor).round(1)
        monthly.loc[sel, "bill_basis"] = "ESTIMATED"
        truth.append({"customer_id": cid, "anomaly_type": "OVERBILLING", "start_date": f"{m}-01",
                      "est_unbilled_kwh": -round(float((monthly.loc[sel, "billed_kwh"] - monthly.loc[sel, "metered_kwh"]).sum()), 1)})
    # Legitimate estimated bills (meter comm failure) with small differences
    est = monthly.sample(frac=0.01, random_state=seed + 1).index
    monthly.loc[est, "bill_basis"] = "ESTIMATED"
    monthly.loc[est, "billed_kwh"] = (monthly.loc[est, "metered_kwh"] * rng.uniform(0.95, 1.08, len(est))).round(1)

    monthly["rate_pkr_per_kwh"] = monthly.tariff.map(RATE_PER_KWH)
    monthly["bill_amount_pkr"] = (monthly.billed_kwh * monthly.rate_pkr_per_kwh).round(0)
    pay_rate = np.where(monthly.tariff == "Agricultural", 0.75, 0.93)
    paid_frac = np.where(rng.random(len(monthly)) < pay_rate, 1.0, rng.uniform(0, 0.6, len(monthly)))
    monthly["amount_paid_pkr"] = (monthly.bill_amount_pkr * paid_frac).round(0)
    monthly["bill_id"] = [f"BILL-{i:07d}" for i in range(1, len(monthly) + 1)]
    billing = monthly[["bill_id", "customer_id", "month", "metered_kwh", "billed_kwh", "bill_basis",
                       "rate_pkr_per_kwh", "bill_amount_pkr", "amount_paid_pkr"]]

    # ---------------- Write ----------------
    events = pd.DataFrame(events).sort_values("event_ts")
    events.insert(0, "event_id", [f"EVT-{i:07d}" for i in range(1, len(events) + 1)])
    truth = pd.DataFrame(truth)
    if "feeder_id" not in truth:
        truth["feeder_id"] = None

    tables = {
        "feeders": feeders, "transformers": transformers,
        "customers": cust[["customer_id", "customer_name", "transformer_id", "feeder_id", "tariff",
                           "sanctioned_load_kw", "meter_id", "meter_type", "connection_date"]],
        "ami_daily_reads": reads.drop(columns="month"),
        "meter_events": events, "feeder_input": feeder_input, "billing": billing,
    }
    for name, df in tables.items():
        df.to_csv(os.path.join(out, f"{name}.csv"), index=False)
    truth.to_csv(os.path.join(out, "ground_truth.csv"), index=False)

    try:
        import duckdb
        db = os.path.join(out, "loss_lens.duckdb")
        if os.path.exists(db):
            os.remove(db)
        con = duckdb.connect(db)
        for name in tables:
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_csv_auto('{os.path.join(out, name + '.csv')}')")
        views = os.path.join(os.path.dirname(os.path.abspath(__file__)), "views.sql")
        if os.path.exists(views):
            con.execute(open(views).read())
        con.close()
        print(f"DuckDB written: {db}")
    except ImportError:
        print("duckdb not installed — CSVs written only")

    print(f"customers={n_customers} days={days} reads={len(reads):,} events={len(events):,}")
    print("planted anomalies:\n" + truth.anomaly_type.value_counts().to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", type=int, default=6000)
    ap.add_argument("--days", type=int, default=92)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
    a = ap.parse_args()
    main(a.customers, a.days, a.seed, a.out)
