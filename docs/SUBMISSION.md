# Loss Lens — Submission Text
*(Copy into the submission form. Adjust headings to match their fields.)*

**Project name:** Loss Lens

**Tagline (one line):**
An AI copilot that finds where electricity is lost or stolen — and who is unfairly overbilled — so honest customers stop paying for everyone else's losses.

**Track:** Digital Solutions, Apps & AI/ML Tools
**Pillar:** Affordability (with Availability as a secondary benefit)
**Customer segment:** Non-residential (distribution utilities), benefiting residential customers

---

## Problem
Distribution companies in Pakistan and many developing markets lose 15–30% of the electricity they buy to theft (hook connections, bypassed or tampered meters) and to faulty metering. These losses are recovered through tariffs, so honest customers pay for stolen power, making electricity less affordable for everyone. Poor estimated billing overcharges vulnerable households too. Utilities already hold the data that reveals this — smart-meter reads, tamper events, feeder energy and billing — but it sits in separate systems and takes analysts days to query.

## Solution
Loss Lens is an AI copilot for utility managers and field teams:
- **Feeder loss ranking:** energy sent in vs energy metered, per feeder and per day, separating normal technical losses from excess loss.
- **Ask in plain English:** questions become SQL; the answer comes with a chart and the query itself, so it can be verified.
- **Ranked inspection list:** risk score with plain-English reasons (e.g. "consumption down 86%; 1 cover-open event"), a consumption chart marked with tamper events, and a one-click field work order in English and Urdu.
- **Fair billing:** finds customers billed far above what their meter recorded, and the refund due.
- **Trust by design:** guardrails allow only read-only queries (8/8 attacks blocked), every action is audit-logged, and it can run on a fully on-premise AI model so customer data never leaves the utility.

## Impact (demo dataset: 30 feeders, 6,000 smart meters, 92 days — synthetic)
- 823 MWh lost above technical losses in 3 months ≈ PKR 45 million — about 6% of all bills, which could come off honest customers' tariffs
- 284 meters prioritised for inspection: 100% precision, 99% recall against the known answer key
- All 5 hook-theft feeders identified; all 72 overbilled customers found (PKR 1.3 million refund due)

Data is synthetic. Real smart-meter data is noisier, which is why Loss Lens always shows its reasons and SQL, and a human approves every inspection.

## Implementation (6–18 months)
- **Months 0–6 — Pilot:** one distribution circle; read-only replica of CIS, AMI and billing data; on-premise AI model; field crews verify the top 100 suspects each month.
- **Months 6–12 — Prove:** measure recovered kWh, refunds issued and complaints resolved; tune the scoring on real inspection outcomes.
- **Months 12–18 — Scale:** all circles; confirmed cases become training labels; loss and overbilling reporting for the regulator.

Costs are low: it runs on existing data and commodity hardware, with no new meters needed. It works anywhere smart meters or even monthly billing data exist — Pakistan, Nigeria, India and beyond.

## How it's built
Python, Streamlit, DuckDB, Plotly; sqlglot-based SQL guardrails; a semantic layer of business views, utility rules and worked examples; works with Claude, OpenAI, Gemini, or local models via Ollama. Includes a synthetic data generator with a planted answer key, so accuracy can be measured.

## Why me
I have 18+ years delivering CIS, billing and smart-metering programs for power utilities — including technical program lead for Pakistan's largest AMI rollout (1.2M+ smart meters at IESCO), and 13 years of SAP IS-U projects at K-Electric. I built Loss Lens because I've seen this data go unused.

**Links:** GitHub repo · Demo video (YouTube, unlisted or public) · LinkedIn: linkedin.com/in/akhterquddus
