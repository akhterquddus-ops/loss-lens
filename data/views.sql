-- Loss Lens semantic layer (DuckDB)
-- The copilot writes SQL against these views only.

-- Monthly energy balance per feeder: energy sent in vs energy metered vs energy billed
CREATE OR REPLACE VIEW v_feeder_loss_monthly AS
WITH inp AS (
    SELECT feeder_id, strftime(read_date, '%Y-%m') AS month, SUM(input_kwh) AS input_kwh
    FROM feeder_input GROUP BY ALL
), met AS (
    SELECT c.feeder_id, strftime(r.read_date, '%Y-%m') AS month, SUM(r.kwh) AS metered_kwh
    FROM ami_daily_reads r JOIN customers c USING (customer_id) GROUP BY ALL
), bil AS (
    SELECT c.feeder_id, b.month, SUM(b.billed_kwh) AS billed_kwh,
           SUM(b.bill_amount_pkr) AS billed_pkr, SUM(b.amount_paid_pkr) AS collected_pkr
    FROM billing b JOIN customers c USING (customer_id) GROUP BY ALL
)
SELECT f.feeder_id, f.feeder_name, f.area, f.area_type, f.substation, inp.month,
       ROUND(inp.input_kwh, 0) AS input_kwh,
       ROUND(met.metered_kwh, 0) AS metered_kwh,
       ROUND(bil.billed_kwh, 0) AS billed_kwh,
       ROUND(100 * (inp.input_kwh - met.metered_kwh) / inp.input_kwh, 2) AS loss_pct,
       f.tech_loss_pct AS expected_technical_loss_pct,
       ROUND(100 * (inp.input_kwh - met.metered_kwh) / inp.input_kwh - f.tech_loss_pct, 2) AS excess_loss_pct,
       ROUND(bil.billed_pkr, 0) AS billed_pkr,
       ROUND(bil.collected_pkr, 0) AS collected_pkr,
       ROUND(100 * bil.collected_pkr / NULLIF(bil.billed_pkr, 0), 1) AS collection_pct
FROM feeders f
JOIN inp USING (feeder_id)
JOIN met USING (feeder_id, month)
LEFT JOIN bil USING (feeder_id, month);

-- Daily feeder balance (for trend charts)
CREATE OR REPLACE VIEW v_feeder_loss_daily AS
SELECT i.feeder_id, i.read_date, i.input_kwh,
       ROUND(SUM(r.kwh), 1) AS metered_kwh,
       ROUND(100 * (i.input_kwh - SUM(r.kwh)) / i.input_kwh, 2) AS loss_pct
FROM feeder_input i
JOIN customers c ON c.feeder_id = i.feeder_id
JOIN ami_daily_reads r ON r.customer_id = c.customer_id AND r.read_date = i.read_date
GROUP BY i.feeder_id, i.read_date, i.input_kwh;

-- Consumption change per customer: first 30 days vs last 30 days, plus zero-read streaks
CREATE OR REPLACE VIEW v_customer_consumption AS
WITH bounds AS (SELECT MIN(read_date) AS d0, MAX(read_date) AS d1 FROM ami_daily_reads),
agg AS (
    SELECT r.customer_id,
           AVG(r.kwh) FILTER (WHERE r.read_date < b.d0 + INTERVAL 30 DAY) AS avg_kwh_first30,
           AVG(r.kwh) FILTER (WHERE r.read_date > b.d1 - INTERVAL 30 DAY) AS avg_kwh_last30,
           AVG(r.kwh) AS avg_daily_kwh,
           COUNT(*) FILTER (WHERE r.kwh = 0 AND r.read_date > b.d1 - INTERVAL 30 DAY) AS zero_days_last30,
           COUNT(*) AS read_days
    FROM ami_daily_reads r, bounds b GROUP BY r.customer_id
)
SELECT c.customer_id, c.customer_name, c.feeder_id, c.transformer_id, c.tariff, c.sanctioned_load_kw,
       ROUND(a.avg_kwh_first30, 2) AS avg_kwh_first30,
       ROUND(a.avg_kwh_last30, 2) AS avg_kwh_last30,
       ROUND(100 * (a.avg_kwh_last30 - a.avg_kwh_first30) / NULLIF(a.avg_kwh_first30, 0), 1) AS change_pct,
       ROUND(a.avg_daily_kwh, 2) AS avg_daily_kwh,
       -- load factor vs sanctioned load: > 0.4 on a residential connection is unusual
       ROUND(a.avg_daily_kwh / (c.sanctioned_load_kw * 24.0), 3) AS load_factor,
       a.zero_days_last30, a.read_days
FROM customers c JOIN agg a USING (customer_id);

-- Tamper-related meter events per customer
CREATE OR REPLACE VIEW v_meter_tamper_events AS
SELECT customer_id, meter_id,
       COUNT(*) FILTER (WHERE event_type IN ('COVER_OPEN', 'TERMINAL_COVER_OPEN')) AS cover_open_events,
       COUNT(*) FILTER (WHERE event_type = 'MAGNETIC_INTERFERENCE') AS magnetic_events,
       COUNT(*) FILTER (WHERE event_type = 'REVERSE_ENERGY') AS reverse_energy_events,
       MIN(event_ts) FILTER (WHERE event_type NOT IN ('POWER_OUTAGE', 'POWER_RESTORED', 'LOW_VOLTAGE')) AS first_tamper_ts
FROM meter_events GROUP BY customer_id, meter_id;

-- Billed vs metered mismatch (overbilling hurts affordability; underbilling hurts revenue)
CREATE OR REPLACE VIEW v_billing_mismatch AS
SELECT b.bill_id, b.customer_id, c.feeder_id, c.tariff, b.month, b.bill_basis,
       b.metered_kwh, b.billed_kwh,
       ROUND(b.billed_kwh - b.metered_kwh, 1) AS diff_kwh,
       ROUND(100 * (b.billed_kwh - b.metered_kwh) / NULLIF(b.metered_kwh, 0), 1) AS diff_pct,
       ROUND((b.billed_kwh - b.metered_kwh) * b.rate_pkr_per_kwh, 0) AS diff_pkr
FROM billing b JOIN customers c USING (customer_id);

-- Inspection priority list: rule-based score with human-readable reasons
CREATE OR REPLACE VIEW v_inspection_list AS
WITH s AS (
    SELECT cc.*, COALESCE(t.cover_open_events, 0) AS cover_open_events,
           COALESCE(t.magnetic_events, 0) AS magnetic_events,
           COALESCE(t.reverse_energy_events, 0) AS reverse_energy_events
    FROM v_customer_consumption cc LEFT JOIN v_meter_tamper_events t USING (customer_id)
)
SELECT customer_id, customer_name, feeder_id, transformer_id, tariff,
       avg_kwh_first30, avg_kwh_last30, change_pct, load_factor, zero_days_last30,
       cover_open_events, magnetic_events, reverse_energy_events,
       (CASE WHEN change_pct <= -50 THEN 35 WHEN change_pct <= -35 THEN 15 ELSE 0 END)
     + (CASE WHEN cover_open_events > 0 AND change_pct <= -35 THEN 30 ELSE 0 END)
     + LEAST(magnetic_events * 8, 40)
     + LEAST(reverse_energy_events * 15, 45)
     + (CASE WHEN zero_days_last30 >= 10 THEN 40 ELSE 0 END)
     + (CASE WHEN tariff = 'Residential' AND load_factor > 0.4 THEN 35 ELSE 0 END) AS risk_score,
       concat_ws('; ',
         CASE WHEN change_pct <= -35 THEN 'consumption down ' || CAST(-change_pct AS VARCHAR) || '%' END,
         CASE WHEN cover_open_events > 0 THEN CAST(cover_open_events AS VARCHAR) || ' cover-open event(s)' END,
         CASE WHEN magnetic_events > 0 THEN CAST(magnetic_events AS VARCHAR) || ' magnetic event(s)' END,
         CASE WHEN reverse_energy_events > 0 THEN 'reverse energy recorded' END,
         CASE WHEN zero_days_last30 >= 10 THEN CAST(zero_days_last30 AS VARCHAR) || ' zero-read days — possible faulty meter' END,
         CASE WHEN tariff = 'Residential' AND load_factor > 0.4 THEN 'load far above sanctioned for residential tariff' END
       ) AS reasons
FROM s;
