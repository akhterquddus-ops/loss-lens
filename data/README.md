# Loss Lens — Synthetic Utility Dataset

A fictional distribution company, **Riverbend Power**: 30 feeders (11 kV), ~300 transformers, 6,000 smart-metered customers and 92 days of data (1 Jul – 30 Sep 2026). **All data is synthetic** — no real customer, meter or utility data.

Regenerate any time:
```bash
pip install pandas numpy duckdb
python generate.py                      # 6,000 customers, seed 42
python generate.py --customers 3000 --seed 7
```
Output goes to `out/`: one CSV per table, `loss_lens.duckdb` (tables + views), and `ground_truth.csv` (the answer key — **never show it to the LLM**).

## Tables
| Table | Grain | Key columns |
|---|---|---|
| `feeders` | feeder | feeder_id, area, area_type (urban/rural/industrial), substation, tech_loss_pct |
| `transformers` | transformer | transformer_id, feeder_id, kva_rating |
| `customers` | customer | customer_id, feeder_id, transformer_id, tariff, sanctioned_load_kw, meter_id |
| `ami_daily_reads` | customer × day | customer_id, meter_id, read_date, kwh (≈1.5% missing reads) |
| `meter_events` | event | customer_id, event_ts, event_type (COVER_OPEN, TERMINAL_COVER_OPEN, MAGNETIC_INTERFERENCE, REVERSE_ENERGY, POWER_OUTAGE, POWER_RESTORED, LOW_VOLTAGE) |
| `feeder_input` | feeder × day | feeder_id, read_date, input_kwh (energy sent into the feeder) |
| `billing` | customer × month | bill_id, month, metered_kwh, billed_kwh, bill_basis (ACTUAL/ESTIMATED), bill_amount_pkr, amount_paid_pkr |

## Views (the semantic layer — the copilot queries these)
| View | Answers |
|---|---|
| `v_feeder_loss_monthly` | Input vs metered vs billed per feeder-month; loss %, excess over expected technical loss, collection % |
| `v_feeder_loss_daily` | Daily trend per feeder |
| `v_customer_consumption` | First-30 vs last-30 day usage, change %, load factor vs sanctioned load, zero-read days |
| `v_meter_tamper_events` | Cover-open, magnetic and reverse-energy event counts per customer |
| `v_billing_mismatch` | Billed vs metered difference in kWh, % and PKR |
| `v_inspection_list` | Risk score with plain-English reasons |

## What's hidden in the data (answer key in `ground_truth.csv`)
| Pattern | Count | Signal |
|---|---|---|
| Hook (kunda) theft feeders | 5 | Feeder loss 27–32% vs ~8–12% normal |
| Meter bypass | 120 | Sudden 55–85% usage drop + cover-open event |
| Magnet tampering | 60 | Intermittent very low reads + magnetic events |
| Reverse connection | 24 | Near-zero usage + reverse-energy events |
| Faulty meter (zero reads) | 36 | Long streak of zero reads (not theft — replace meter) |
| Tariff misuse | 48 | Residential connection with commercial-scale load |
| Overbilling | 72 | Estimated bill 1.6–3× metered usage |

Decoys are included: honest customers with outage events and legitimate cover-open (maintenance) events, normal seasonal decline (~25% from July to September), and small legitimate estimated-bill differences.

## Baseline detection (rules only, before any AI)
- All 5 hook-theft feeders rank top 5 by excess loss
- Inspection list (risk_score ≥ 30): 284 flagged, **precision 100%, recall 98.6%**
- Billing mismatch (≥ 30%): finds all 72 overbilled customers

## Sample questions for the copilot
1. Which five feeders had the highest excess loss in September?
2. Show the daily input vs metered energy for FDR-024.
3. Which customers' consumption dropped more than 50% and had a cover-open event?
4. List residential customers using far more than their sanctioned load.
5. How many meters have read zero for 10+ days in the last month? Which feeders are they on?
6. Which customers were overbilled, and by how many rupees in total?
7. What is the collection rate by area type?
8. Give me the top 20 inspection targets on Chak 12 feeders, with reasons.
9. How much energy (kWh and PKR) are we losing above technical losses each month?
10. Compare loss % between urban and rural feeders.

## Quick SQL to try
```sql
SELECT feeder_id, area, ROUND(AVG(loss_pct),1) AS loss_pct, ROUND(AVG(excess_loss_pct),1) AS excess
FROM v_feeder_loss_monthly GROUP BY ALL ORDER BY excess DESC LIMIT 5;

SELECT customer_id, feeder_id, risk_score, reasons
FROM v_inspection_list WHERE risk_score >= 30 ORDER BY risk_score DESC LIMIT 20;
```
