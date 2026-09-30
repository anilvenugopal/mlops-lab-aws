# Data dictionary

Column-level reference for the 11 tables `generate.py` produces. This is
**source data**, not features — it describes what a carrier's policy admin
and claims systems would hold. Feature definitions live separately in
`../features/` (Feast); this file has nothing to do with the feature store.
See [README.md](README.md) for table grain, keys, and the ER diagram.

Types shown are the Parquet/pandas dtype as written by `generate.py`.
"Domain" lists every value a categorical column can take; open-ended columns
(ids, amounts, free dates) have no domain and are left blank.

---

## The three roles a table plays

Tables here are not just "input" and "ground truth." There is a third,
distinct role, and conflating it with either of the first two is a mistake
worth naming explicitly:

| Role | Known at scoring time? | Can a model be trained on it? | Tables |
|---|---|---|---|
| **Reference / dimension** | yes | yes | `customer`, `policy`, `vehicle`, `salvage_market` — static or slow-changing facts that other tables hang off of |
| **Input** | yes | yes | `claim`, `vehicle_valuation` — what was known and knowable at FNOL / scoring time |
| **Feedback (human review)** | no — arrives after scoring, and is itself unverified | **no** — see below | `adjuster_decision` |
| **Ground truth** | no — known only after the fact | no, by definition (it's the target, not a feature) | `claim_truth`, `outcome_label` |
| Operational record (not modeled) | n/a | n/a | `claim_event`, `claim_financial` — the event/money trail that `claim_truth` and `outcome_label` are computed from |

**`adjuster_decision` is feedback, not ground truth, and not input.** It is
an adjuster's *opinion*, captured at override time, that the model's
decision was wrong — before anyone knows whether the adjuster was right.
Concretely: `human_decision` is what the adjuster thinks the answer should
have been, and `suspected_feature` / `reason_code` is what the adjuster
*blames*. Neither is verified at the moment it's recorded. The
`adjuster_was_wrong` column exists precisely so you can go check —
`generate.py` computes it by comparing `human_decision` back to
`claim_truth.truth_is_total_loss`, and about 30% of the time the adjuster
turns out to be the one who was wrong.

This is what SETUP.md capability 7 ("Feedback and root cause") and demo
move 4 are built around: an adjuster overrides the model and blames a
feature (`adjuster_decision`); the platform's job is not to defer to that
opinion, but to let you **replay what the model actually saw** and check
the allegation against it. Sometimes the allegation is correct (fault 2,
the stale valuation) and sometimes the adjuster is simply wrong. Training a
model on `adjuster_decision.human_decision` as if it were a label would be
training on an unverified opinion — exactly the trap the table exists to
let you demonstrate, not fall into.

---

## Reference / dimension tables

Static or slow-changing entities that `claim` and `vehicle_valuation` hang
off of. Known at scoring time; safe to use as feature inputs.

## customer

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `customer_id` | string | no | `CUST-######`, primary key |
| `state` | string | no | `MA`, `CT`, `NJ`, `NH`, `PA` |
| `credit_band` | string | no | `A`, `B`, `C`, `D`, `E` (A = best) |
| `customer_since` | timestamp (UTC) | no | Can predate `start_date` by up to 12 years — tenure existed before the observation window began |
| `birth_year` | int | no | 1945–2005 |

## policy

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `policy_id` | string | no | `POL-#######`, primary key |
| `customer_id` | string | no | FK → `customer` |
| `state` | string | no | Same domain as `customer.state`; copied onto the policy at issue |
| `effective_date` | timestamp (UTC) | no | Term start |
| `expiry_date` | timestamp (UTC) | no | Always `effective_date + 365 days` |
| `annual_premium` | float | no | USD, clipped to [520, 5200] |
| `collision_deductible` | int | no | 250, 500, 1000, 2000 |
| `comprehensive_deductible` | int | no | 100, 250, 500, 1000 |
| `has_rental` | bool | no | Rental reimbursement coverage present |
| `has_roadside` | bool | no | Roadside assistance coverage present |

## vehicle

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `vehicle_id` | string | no | `VEH-#######`, primary key |
| `policy_id` | string | no | FK → `policy` |
| `customer_id` | string | no | FK → `customer`; denormalized from `policy` |
| `vin` | string | no | Synthetic 17-character string, not a valid VIN checksum |
| `model_year` | int | no | 2012–2026 |
| `segment` | string | no | `economy`, `mid`, `luxury` |
| `msrp` | float | no | USD at time of manufacture; static, does not depreciate |
| `mileage_est` | float | **yes (~20%)** | Deliberate missingness — see README "Missing data" — informative, not random |
| `added_date` | timestamp | no | Equals the owning policy's `effective_date` |

**No ACV column.** Vehicle value is temporal and lives in `vehicle_valuation`,
never on this row.

## salvage_market

One row per calendar month. No foreign key — joined to claims by nearest
month inside the generator, not carried through as a relationship.

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `month` | timestamp (UTC) | no | First of month, primary key |
| `used_value_index` | float | no | Base 100 at `start_date`, drifts monthly, rises in the final quarter — see README's note on feature vs. concept drift |

---

## Input tables

What was known and knowable at FNOL / scoring time. Safe to build features
from.

## vehicle_valuation

One row per **valuation event**, not per vehicle. Key is
`(vehicle_id, valuation_datetime)`.

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `valuation_id` | string | no | `VAL-########`, primary key |
| `vehicle_id` | string | no | FK → `vehicle` |
| `valuation_datetime` | timestamp (UTC) | no | When this valuation became current |
| `acv` | float | no | Actual cash value in USD as of `valuation_datetime` |
| `source` | string | no | `quarterly_book` (routine, one per vehicle per quarter), `vendor_feed` (struck at FNOL for a claimed vehicle), `vendor_feed_stale` (FNOL valuation, deliberately understated — see README fault 2), `vendor_feed_corrected` (the correction that follows a stale valuation, days later) |
| `supersedes_reason` | string | yes (all but corrections) | Only set on `vendor_feed_corrected` rows, value `stale_valuation_corrected` |

## claim

FNOL-time facts only. No ground truth, no outcome — see `claim_truth` for that.

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `claim_id` | string | no | `CLM-#######`, primary key |
| `policy_id` | string | no | FK → `policy` |
| `vehicle_id` | string | no | FK → `vehicle` |
| `customer_id` | string | no | FK → `customer` |
| `state` | string | no | Copied from the policy at loss time |
| `loss_datetime` | timestamp (UTC) | no | When the loss occurred; nudged toward 07:00–21:00 local (FNOL calls cluster in waking hours) |
| `fnol_datetime` | timestamp (UTC) | no | Always ≥ `loss_datetime`; lag is exponential, most within hours, a tail out to 21 days |
| `cause_of_loss` | string | no | `collision`, `comprehensive`, `glass`, `theft`, `animal` |
| `reported_severity` | int | no | 1 (minor) – 5 (severe), as reported at FNOL |
| `airbag_deployed` | bool | no | More likely at severity ≥ 4 |
| `vehicle_drivable` | bool | no | False implies higher severity or airbag deployment |
| `towed_from_scene` | bool | no | Usually true when not drivable |
| `injury_reported` | bool | no | |
| `at_fault` | bool | no | Whether the insured was at fault |
| `num_vehicles_involved` | int | no | 1–3 for `collision`; always 1 for every other cause |

---

## Ground truth tables

Known only after the fact. Never a model input — this is what a model is
trained to predict and evaluated against, not what it sees.

## claim_truth

**Never a model input** — kept separate from `claim` specifically so it
can't be joined into a feature view by accident. One row per claim, 1:1
with `claim`.

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `claim_id` | string | no | Primary key, FK → `claim` |
| `truth_acv` | float | no | The vehicle's true actual cash value at loss date, USD |
| `truth_repair_estimate` | float | no | True repair cost before any supplement, USD |
| `truth_supplement` | float | no | Additional repair cost found after teardown, USD (0 if none) |
| `truth_repair_total` | float | no | `truth_repair_estimate + truth_supplement` |
| `truth_tlt` | float | no | The statutory total-loss threshold actually applied (accounts for the MA rate change — see README fault 1) |
| `truth_is_total_loss` | bool | no | `truth_repair_total / truth_acv >= truth_tlt`, excluding glass claims |

## outcome_label

Append-only. One row per `(claim_id, label_type, label_as_of_date)` — a
claim accumulates rows as each horizon it's eligible for elapses. A claim
reported late in the data window may have fewer rows than an older one,
because a horizon that hasn't been reached yet by `end_date` has no row at
all (there is no label to report).

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `outcome_id` | string | no | `OUT-########`, primary key |
| `claim_id` | string | no | FK → `claim` |
| `label_type` | string | no | `incurred_net` (net paid, at 30/90/365 days), `total_loss` (the eventual decision, at 45 days) |
| `label_value` | float | no | USD for `incurred_net`; 0.0/1.0 for `total_loss` |
| `label_as_of_date` | timestamp (UTC) | no | The date this label became knowable — `fnol_datetime + label_maturity_days`, never later than `end_date` |
| `label_maturity_days` | int | no | 30, 90, 365 (`incurred_net`) or 45 (`total_loss`) |
| `is_final` | bool | no | True only for the 365-day `incurred_net` row and every `total_loss` row |

---

## Operational record tables

The event and money trail. Not modeled directly — `claim_truth` and
`outcome_label` are computed from these, but a model never reads
`claim_event` or `claim_financial` rows itself.

## claim_event

One row per lifecycle event. `payload` is a JSON string whose shape depends
on `event_type` — see the table below.

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `event_id` | string | no | `EVT-########`, primary key |
| `claim_id` | string | no | FK → `claim` |
| `event_type` | string | no | See payload shapes below |
| `event_datetime` | timestamp (UTC) | no | |
| `payload` | string (JSON) | yes | Null for `CLAIM_CLOSED`; parse per `event_type` |

**`event_type` domain and `payload` shape** (every claim gets the first six;
the rest are conditional):

| `event_type` | Always present? | `payload` example |
|---|---|---|
| `FNOL_REPORTED` | yes | `{"channel": "phone"}` |
| `ADJUSTER_ASSIGNED` | yes | `{"adjuster_id": "ADJ-017"}` |
| `RESERVE_SET` | yes | `{"amount": 1024.0}` |
| `ESTIMATE_RECEIVED` | yes | `{"amount": 1227.0}` |
| `SETTLEMENT_PAID` | yes | `{"amount": 727.0}` |
| `CLAIM_CLOSED` | yes | `null` |
| `PHOTOS_UPLOADED` | no (~78% of claims) | `{"photo_count": 6, "photo_damage_score": 0.2389, "photo_quality": 0.552}` — `photo_damage_score` stands in for a vision model's output; see README fault 5 |
| `SUPPLEMENT_ADDED` | no (~30%) | `{"amount": 1485.0}` |
| `TOTAL_LOSS_DECLARED` | no (~18%, when `truth_is_total_loss`) | `{"acv": 13475.0}` |
| `SALVAGE_VALUED` | no (pairs with `TOTAL_LOSS_DECLARED`) | `{"amount": 2948.0}` |
| `SUBROGATION_RECOVERED` | no (~19%, not-at-fault claims only) | see `claim_financial.RECOVERY` for the amount |

## claim_financial

One row per money movement. Summing `amount` per claim gives net incurred,
because `RECOVERY` rows are stored negative.

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `txn_id` | string | no | `FIN-########`, primary key |
| `claim_id` | string | no | FK → `claim` |
| `txn_type` | string | no | `RESERVE` (one per claim, set at adjuster assignment), `PAYMENT` (one per claim, the settlement), `RECOVERY` (subrogation only, **negative** amount) |
| `amount` | float | no | USD; positive except `RECOVERY` |
| `txn_datetime` | timestamp (UTC) | no | |

---

## Feedback table

Neither input nor ground truth — see "The three roles a table plays" above.
A human's unverified opinion, captured at override time.

## adjuster_decision

One row per human override of a model decision. Not every claim has one
(~19% do).

| Column | Type | Nullable | Domain / notes |
|---|---|---|---|
| `decision_id` | string | no | `DEC-#######`, primary key |
| `claim_id` | string | no | FK → `claim` |
| `adjuster_id` | string | no | `ADJ-###`, one of 24 |
| `decision_datetime` | timestamp (UTC) | no | |
| `human_decision` | string | no | `total_loss`, `repairable` — the adjuster's call, which **contradicts** `claim_truth.truth_is_total_loss` by construction (this table only exists for overrides) |
| `reason_code_family` | string | no | `feature`, `model`, `process` |
| `reason_code` | string | no | Within `feature`: `feature_value_wrong`, `stale_features`, `feature_missing`. Within `model`: `score_too_harsh`, `score_too_soft`, `unstable_vs_last_week`. Within `process`: `policy_exception`, `customer_goodwill`, `missing_document` |
| `suspected_feature` | string | yes (~81%) | `vehicle_acv` when set — only populated for a subset of `feature`-family overrides |
| `adjuster_was_wrong` | bool | no | Whether this override itself turned out to be incorrect (~30% are) |
