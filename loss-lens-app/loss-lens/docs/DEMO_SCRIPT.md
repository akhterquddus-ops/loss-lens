# Loss Lens — Demo Video Script (≈3 minutes)

**Setup before recording**
- Run `streamlit run app\app.py`, browser full screen, zoom 110%
- Record with **Win + Alt + R** (Xbox Game Bar) or OBS; use a headset mic
- Close notifications. Do one practice run first.
- Speak slowly. It's fine to pause the recording between scenes.

---

### 1 · The problem (0:00–0:25) — Overview tab, top of page
> "In Pakistan and across much of the world, distribution companies lose 15 to 30 percent of their electricity to theft and faulty meters. Those losses go into the tariff — so honest customers pay for stolen power. I've spent 18 years in utility billing and smart metering, including Pakistan's largest smart-meter rollout. Utilities already have the data to fix this. Loss Lens makes that data answer questions."

### 2 · Where the energy goes (0:25–0:55) — Overview
- Point to the five KPIs. Hover the bar chart; the tall orange bars are the rural feeders.
- Pick **FDR-024 · Chak 12** in the drill-down.
> "This utility loses 12.9 percent overall, but five feeders lose 25 to 32 percent. Here's Chak 12: the black line is energy sent in, the orange line is energy metered. That gap, every day, is stolen power — about 45 million rupees in three months, or 6 percent of every bill."

### 3 · Ask in plain English (0:55–1:30) — Ask tab
- Click **"Which customers' consumption dropped more than 50% and had a cover-open event?"** → Ask.
- Open **SQL behind this answer**.
> "A manager doesn't need to write SQL. They ask, and Loss Lens shows the answer, a chart, and the exact query — so the result can be checked, not just trusted."
- *(If AI is on, type your own question, e.g. "Which rural feeders have the worst collection rate?")*

### 4 · Send the crews to the right houses (1:30–2:10) — Inspection list
- Point to the risk score and the **reasons** column.
- In **Customer**, type **CUST-000188** and select it. The chart shows usage collapsing right after the cover-open event on 21 August.
- Click **Generate field work order**.
> "Instead of random raids, field crews get a ranked list with reasons a person can verify. This customer's usage fell 86 percent — right after the meter cover was opened on 21 August. One click creates the work order for the inspector."

### 5 · Fairness (2:10–2:30) — Fair billing
> "Affordability works both ways. Loss Lens also finds 72 households billed up to three times what their meter recorded — 1.3 million rupees to refund. Those are usually the people who can least afford it."

### 6 · Trust (2:30–2:50) — Ask → Try to break it, then Accuracy
- Click **Delete billing records**, then **Read environment secrets** — both blocked.
- Switch to **Accuracy**.
> "It can't change data or read secrets — every query passes guardrails and is logged. And we test it: against the known answer key it finds all five hook-theft feeders, 99 percent of tampered meters with no false alarms, and every overbilled customer."

### 7 · Close (2:50–3:05)
> "Loss Lens can run fully on-premise, so customer data never leaves the utility. A pilot on one distribution circle can start within six months. Less theft, fair bills, lower tariffs for honest customers. Thank you."

---

**If short on time:** cut scene 5 to one sentence, and skip the work order.
