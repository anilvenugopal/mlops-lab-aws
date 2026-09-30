#!/usr/bin/env python3
"""
Synthetic P&C source data for the ML platform lab.

Produces the tables a carrier's policy admin and claims systems would hold —
NOT features. Features are derived from these by the Glue pipelines.

The point of this generator is not realistic-looking data. It is data with the
specific properties a feature platform demo needs:

  * every fact carries an event timestamp, so point-in-time joins are meaningful
  * values change over time, so the offline store is a history and not a snapshot
  * labels mature at different rates, so "what turned out true" depends on when
    you ask
  * a handful of deliberate faults, so the root-cause demo has something to find

Run:  python generate.py --config config.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

SECONDS_PER_DAY = 86_400


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def rand_datetimes(rng, start: pd.Timestamp, end: pd.Timestamp, n: int) -> pd.Series:
    """Uniform random timestamps in [start, end), second resolution."""
    lo = int(start.timestamp())
    hi = int(end.timestamp())
    return pd.Series(pd.to_datetime(rng.integers(lo, hi, size=n), unit="s", utc=True))


def business_hours_shift(ts: pd.Series, rng) -> pd.Series:
    """
    Nudge timestamps toward waking hours. FNOL calls cluster 07:00-21:00 local;
    a uniform distribution over the clock looks wrong to anyone who has worked
    in claims.
    """
    hours = ts.dt.hour
    nudge = np.where(hours < 7, rng.integers(7, 12, len(ts)) - hours,
            np.where(hours > 21, rng.integers(14, 21, len(ts)) - hours, 0))
    return ts + pd.to_timedelta(nudge, unit="h")


def lognormal_ratio(rng, mu, sigma, n):
    return np.exp(rng.normal(mu, sigma, n))


def pick(rng, mapping: dict, n: int):
    """Weighted choice from {value: weight}."""
    keys = list(mapping.keys())
    weights = np.array([mapping[k] for k in keys], dtype=float)
    weights = weights / weights.sum()
    return rng.choice(keys, size=n, p=weights)


# --------------------------------------------------------------------------- #
# generator
# --------------------------------------------------------------------------- #

@dataclass
class Generator:
    cfg: dict

    def __post_init__(self):
        self.rng = np.random.default_rng(self.cfg["seed"])
        self.start = pd.Timestamp(self.cfg["start_date"], tz="UTC")
        self.end = pd.Timestamp(self.cfg["end_date"], tz="UTC")
        self.tables: dict[str, pd.DataFrame] = {}

    # ----------------------------------------------------------- customers
    def gen_customers(self) -> pd.DataFrame:
        n = self.cfg["n_customers"]
        rng = self.rng
        state_weights = {k: v["weight"] for k, v in self.cfg["states"].items()}

        # Tenure start can predate the data window — customers existed before we
        # started observing them. Without this, tenure is uniformly short and the
        # tenure feature carries no signal.
        tenure_start = self.start - pd.to_timedelta(
            rng.integers(0, 365 * 12, n), unit="D"
        )

        df = pd.DataFrame({
            "customer_id": [f"CUST-{i:06d}" for i in range(1, n + 1)],
            "state": pick(rng, state_weights, n),
            "credit_band": pick(rng, {"A": .22, "B": .31, "C": .27, "D": .14, "E": .06}, n),
            "customer_since": tenure_start,
            "birth_year": rng.integers(1945, 2006, n),
        })
        return df

    # ------------------------------------------------------------ policies
    def gen_policies(self, customers: pd.DataFrame) -> pd.DataFrame:
        n = self.cfg["n_policies"]
        rng = self.rng

        # Renewals: some customers hold several consecutive annual terms.
        owner_idx = rng.integers(0, len(customers), n)
        owners = customers.iloc[owner_idx].reset_index(drop=True)

        eff = rand_datetimes(rng, self.start - pd.Timedelta(days=365), self.end, n).dt.normalize()

        df = pd.DataFrame({
            "policy_id": [f"POL-{i:07d}" for i in range(1, n + 1)],
            "customer_id": owners["customer_id"].values,
            "state": owners["state"].values,
            "effective_date": eff,
            "expiry_date": eff + pd.Timedelta(days=365),
            "annual_premium": np.round(rng.normal(1480, 420, n).clip(520, 5200), 2),
            "collision_deductible": pick(rng, {250: .18, 500: .48, 1000: .29, 2000: .05}, n),
            "comprehensive_deductible": pick(rng, {100: .12, 250: .34, 500: .41, 1000: .13}, n),
            "has_rental": rng.random(n) < 0.63,
            "has_roadside": rng.random(n) < 0.55,
        })
        return df

    # ------------------------------------------------------------ vehicles
    def gen_vehicles(self, policies: pd.DataFrame) -> pd.DataFrame:
        n = self.cfg["n_vehicles"]
        rng = self.rng
        vcfg = self.cfg["vehicle"]

        pol_idx = rng.integers(0, len(policies), n)
        pol = policies.iloc[pol_idx].reset_index(drop=True)

        segment = pick(rng, vcfg["segment_mix"], n)
        msrp = np.empty(n)
        for seg, (lo, hi) in vcfg["msrp_by_segment"].items():
            m = segment == seg
            msrp[m] = rng.uniform(lo, hi, m.sum())

        yr_lo, yr_hi = vcfg["model_year_range"]
        model_year = rng.integers(yr_lo, yr_hi + 1, n)

        # INJECTED FLAW 3: mileage unknown for a fifth of the book. Missingness
        # is itself informative — an older vehicle with no odometer reading is a
        # different risk from an older vehicle with a known low reading.
        mileage = (2026 - model_year) * rng.normal(11500, 3200, n).clip(3000, 25000)
        miss = rng.random(n) < self.cfg["missingness"]["mileage_missing_share"]
        mileage = np.where(miss, np.nan, np.round(mileage, -2))

        df = pd.DataFrame({
            "vehicle_id": [f"VEH-{i:07d}" for i in range(1, n + 1)],
            "policy_id": pol["policy_id"].values,
            "customer_id": pol["customer_id"].values,
            "vin": [f"1{rng.integers(10**15, 10**16 - 1)}"[:17] for _ in range(n)],
            "model_year": model_year,
            "segment": segment,
            "msrp": np.round(msrp, 0),
            "mileage_est": mileage,
            "added_date": pol["effective_date"].values,
        })
        return df

    # -------------------------------------------------------- market index
    def gen_salvage_market(self) -> pd.DataFrame:
        """
        Monthly used-vehicle value index. Drifts gently, then rises in the final
        quarter. This produces mild FEATURE drift — useful contrast against the
        statutory change, which produces CONCEPT drift with no feature movement.
        """
        rng = self.rng
        months = pd.date_range(self.start, self.end, freq="MS", tz="UTC")
        base = 100 + np.cumsum(rng.normal(0.15, 0.9, len(months)))
        late = months >= (self.end - pd.Timedelta(days=95))
        base = base + np.where(late, np.linspace(0, 11, len(months)) * late, 0)
        return pd.DataFrame({"month": months, "used_value_index": np.round(base, 2)})

    # -------------------------------------------------------- total loss threshold
    def tlt_for(self, state: np.ndarray, when: pd.Series) -> np.ndarray:
        """
        Statutory total-loss threshold, as it stood on the loss date.

        INJECTED FLAW 1 — concept drift. One state lowers its threshold partway
        through the window. Nothing about the input features changes; the
        mapping from features to outcome does. A drift monitor watching feature
        distributions will see nothing at all.
        """
        base = np.array([self.cfg["states"][s]["tlt"] for s in state])
        ch = self.cfg["tlt_change"]
        if not ch["enabled"]:
            return base
        eff = pd.Timestamp(ch["effective_date"], tz="UTC")
        changed = (state == ch["state"]) & (when >= eff).values
        return np.where(changed, ch["new_tlt"], base)

    # ------------------------------------------------------------- claims
    def gen_claims(self, customers, policies, vehicles, market) -> tuple:
        n = self.cfg["n_claims"]
        rng = self.rng
        ccfg = self.cfg["claim"]
        vcfg = self.cfg["vehicle"]

        veh_idx = rng.integers(0, len(vehicles), n)
        veh = vehicles.iloc[veh_idx].reset_index(drop=True)
        pol = policies.set_index("policy_id").loc[veh["policy_id"]].reset_index()

        loss_dt = rand_datetimes(rng, self.start, self.end, n)
        loss_dt = business_hours_shift(loss_dt, rng)
        # FNOL lags the loss: most within hours, a tail of days.
        fnol_lag_h = np.clip(rng.exponential(9, n), 0.2, 24 * 21)
        fnol_dt = loss_dt + pd.to_timedelta(fnol_lag_h, unit="h")

        cause = pick(rng, ccfg["cause_mix"], n)
        severity = np.clip(rng.integers(1, 6, n), 1, 5)
        # Comprehensive and glass skew to lower severity.
        severity = np.where(np.isin(cause, ["glass", "animal"]),
                            np.clip(severity - 1, 1, 5), severity)

        # ---- true ACV at the loss date -------------------------------------
        age_years = np.maximum(loss_dt.dt.year.values - veh["model_year"].values, 0)
        dep = (1 - vcfg["annual_depreciation"]) ** age_years
        floor = vcfg["floor_value_pct"]
        acv_base = veh["msrp"].values * np.maximum(dep, floor)

        # market index moves value
        midx = market.set_index("month")["used_value_index"]
        m_key = pd.to_datetime(loss_dt.dt.strftime("%Y-%m-01")).dt.tz_localize("UTC")
        m_factor = midx.reindex(m_key).ffill().bfill().values / 100.0
        acv_true = np.round(acv_base * m_factor, 0)

        # ---- repair estimate ------------------------------------------------
        mu = np.array(ccfg["repair_ratio_mu"])[severity - 1]
        sg = np.array(ccfg["repair_ratio_sigma"])[severity - 1]
        repair_ratio = lognormal_ratio(rng, mu, sg, n)
        repair_estimate = np.round(acv_true * repair_ratio, 0).clip(250, None)

        # ---- supplement -----------------------------------------------------
        has_supp = rng.random(n) < ccfg["supplement_share"]
        up_lo, up_hi = ccfg["supplement_uplift"]
        supp_amt = np.where(has_supp,
                            np.round(repair_estimate * rng.uniform(up_lo, up_hi, n), 0), 0.0)
        repair_total = repair_estimate + supp_amt

        # ---- the total loss decision ---------------------------------------
        tlt = self.tlt_for(pol["state"].values, loss_dt)
        is_total = (repair_total >= acv_true * tlt) & (cause != "glass")

        at_fault = rng.random(n) < ccfg["at_fault_share"]
        injury = rng.random(n) < ccfg["injury_share"]
        airbag = (severity >= 4) & (rng.random(n) < 0.72)
        drivable = ~((severity >= 4) | (airbag & (rng.random(n) < 0.9)))
        towed = ~drivable & (rng.random(n) < 0.93)

        claims = pd.DataFrame({
            "claim_id": [f"CLM-{i:07d}" for i in range(1, n + 1)],
            "policy_id": veh["policy_id"].values,
            "vehicle_id": veh["vehicle_id"].values,
            "customer_id": veh["customer_id"].values,
            "state": pol["state"].values,
            "loss_datetime": loss_dt,
            "fnol_datetime": fnol_dt,
            "cause_of_loss": cause,
            "reported_severity": severity,
            "airbag_deployed": airbag,
            "vehicle_drivable": drivable,
            "towed_from_scene": towed,
            "injury_reported": injury,
            "at_fault": at_fault,
            "num_vehicles_involved": np.where(cause == "collision",
                                              rng.integers(1, 4, n), 1),
            # ground truth, not available at FNOL — kept for label construction
            "truth_acv": acv_true,
            "truth_repair_estimate": repair_estimate,
            "truth_supplement": supp_amt,
            "truth_repair_total": repair_total,
            "truth_tlt": tlt,
            "truth_is_total_loss": is_total,
        })
        return claims

    # ------------------------------------------------------- valuations
    def gen_valuations(self, vehicles, claims) -> pd.DataFrame:
        """
        Vehicle valuations over time. This table — not the vehicle row — is where
        ACV lives, because ACV is a temporal fact.

        INJECTED FLAW 2. For a slice of claims the valuation current at FNOL is
        understated and is corrected days later. Replaying that feature today
        returns the corrected value, which will not match what the model saw.
        That mismatch is the whole root-cause demo.
        """
        rng = self.rng
        scfg = self.cfg["stale_acv"]
        rows = []

        # routine quarterly valuations for every vehicle
        veh = vehicles[["vehicle_id", "msrp", "model_year", "added_date"]].copy()
        quarters = pd.date_range(self.start, self.end, freq="QS", tz="UTC")
        dep = self.cfg["vehicle"]["annual_depreciation"]
        floor = self.cfg["vehicle"]["floor_value_pct"]

        for q in quarters:
            age = np.maximum(q.year - veh["model_year"].values, 0)
            val = veh["msrp"].values * np.maximum((1 - dep) ** age, floor)
            val = np.round(val * rng.normal(1.0, 0.03, len(veh)), 0)
            rows.append(pd.DataFrame({
                "vehicle_id": veh["vehicle_id"].values,
                "valuation_datetime": q,
                "acv": val,
                "source": "quarterly_book",
                "supersedes_reason": None,
            }))

        val_df = pd.concat(rows, ignore_index=True)

        # a per-claim valuation struck at FNOL, which is what serving reads
        c = claims[["claim_id", "vehicle_id", "fnol_datetime", "truth_acv"]].copy()
        stale_mask = np.zeros(len(c), dtype=bool)
        if scfg["enabled"]:
            k = int(len(c) * scfg["share_of_claims"])
            stale_mask[rng.choice(len(c), k, replace=False)] = True

        lo, hi = scfg["understate_pct"]
        understate = rng.uniform(lo, hi, len(c))
        acv_at_fnol = np.where(stale_mask,
                               np.round(c["truth_acv"].values * (1 - understate), 0),
                               c["truth_acv"].values)

        fnol_vals = pd.DataFrame({
            "vehicle_id": c["vehicle_id"].values,
            "valuation_datetime": pd.to_datetime(c["fnol_datetime"].values, utc=True),
            "acv": acv_at_fnol,
            "source": np.where(stale_mask, "vendor_feed_stale", "vendor_feed"),
            "supersedes_reason": None,
        })

        # corrections land a few days later for the stale ones
        lag_lo, lag_hi = scfg["correction_lag_days"]
        corr_idx = np.where(stale_mask)[0]
        corrections = pd.DataFrame({
            "vehicle_id": c["vehicle_id"].values[corr_idx],
            "valuation_datetime": (
                pd.to_datetime(c["fnol_datetime"].values[corr_idx], utc=True)
                + pd.to_timedelta(rng.integers(lag_lo, lag_hi + 1, len(corr_idx)), unit="D")
            ),
            "acv": c["truth_acv"].values[corr_idx],
            "source": "vendor_feed_corrected",
            "supersedes_reason": "stale_valuation_corrected",
        })

        out = pd.concat([val_df, fnol_vals, corrections], ignore_index=True)
        out["valuation_datetime"] = pd.to_datetime(out["valuation_datetime"], utc=True)
        out = out.sort_values(["vehicle_id", "valuation_datetime"]).reset_index(drop=True)
        out["valuation_id"] = [f"VAL-{i:08d}" for i in range(1, len(out) + 1)]

        # expose which claims were affected so the demo can find them fast
        self._stale_claims = c.loc[stale_mask, "claim_id"].tolist()
        return out[["valuation_id", "vehicle_id", "valuation_datetime", "acv",
                    "source", "supersedes_reason"]]

    # ---------------------------------------------------------- lifecycle
    def gen_lifecycle(self, claims) -> tuple:
        """
        Claim events, money, and human decisions. Produces the event stream that
        makes label maturity real: the same claim has a different incurred
        amount at 30, 90 and 365 days.
        """
        rng = self.rng
        acfg = self.cfg["adjuster"]
        pcfg = self.cfg["photo_model"]
        subcfg = self.cfg["subrogation"]

        events, financials, decisions = [], [], []
        adjusters = [f"ADJ-{i:03d}" for i in range(1, acfg["n_adjusters"] + 1)]
        drift_after = pd.Timestamp(pcfg["bias_drift_after"], tz="UTC")

        n = len(claims)
        never_photos = rng.random(n) < self.cfg["missingness"]["photos_never_uploaded_share"]
        overrides = rng.random(n)
        reason_family = pick(rng, acfg["reason_mix"], n)
        adj_wrong = rng.random(n) < acfg["adjuster_wrong_rate"]
        do_subro = (~claims["at_fault"].values) & (
            rng.random(n) < subcfg["share_of_not_at_fault"])

        rec_lo, rec_hi = subcfg["recovery_pct"]
        sub_lo, sub_hi = subcfg["lag_days"]

        for i, row in enumerate(claims.itertuples(index=False)):
            cid = row.claim_id
            fnol = pd.Timestamp(row.fnol_datetime)

            def ev(kind, when, payload=None):
                events.append({
                    "claim_id": cid, "event_type": kind,
                    "event_datetime": when,
                    "payload": json.dumps(payload) if payload else None,
                })

            ev("FNOL_REPORTED", fnol, {"channel": "phone"})

            # ---- photos: present, pending, or never --------------------------
            if not never_photos[i]:
                photo_t = fnol + pd.Timedelta(hours=float(rng.exponential(6) + 0.5))
                true_dmg = row.reported_severity / 5.0
                bias = pcfg["bias_drift_amount"] if fnol >= drift_after else 0.0
                score = float(np.clip(
                    true_dmg + rng.normal(bias, pcfg["noise_sd"]), 0.01, 0.99))
                ev("PHOTOS_UPLOADED", photo_t, {
                    "photo_count": int(rng.integers(3, 12)),
                    "photo_damage_score": round(score, 4),
                    "photo_quality": round(float(rng.uniform(0.5, 1.0)), 3),
                })

            adj_t = fnol + pd.Timedelta(days=float(rng.uniform(0.5, 3)))
            adjuster = adjusters[int(rng.integers(0, len(adjusters)))]
            ev("ADJUSTER_ASSIGNED", adj_t, {"adjuster_id": adjuster})

            # ---- initial reserve ---------------------------------------------
            reserve = float(np.round(row.truth_repair_estimate * rng.uniform(0.7, 1.1), 0))
            ev("RESERVE_SET", adj_t, {"amount": reserve})
            financials.append({"claim_id": cid, "txn_type": "RESERVE",
                               "amount": reserve, "txn_datetime": adj_t})

            est_t = fnol + pd.Timedelta(days=float(rng.uniform(3, 9)))
            ev("ESTIMATE_RECEIVED", est_t, {"amount": float(row.truth_repair_estimate)})

            if row.truth_supplement > 0:
                sup_t = est_t + pd.Timedelta(days=float(rng.uniform(4, 16)))
                ev("SUPPLEMENT_ADDED", sup_t, {"amount": float(row.truth_supplement)})

            # ---- the adjuster's decision, which may contradict the model -----
            is_dec = overrides[i] < (
                acfg["base_override_rate"]
                * (acfg["december_override_multiplier"] if fnol.month == 12 else 1.0)
            )
            if is_dec:
                dec_t = adj_t + pd.Timedelta(hours=float(rng.uniform(1, 48)))
                fam = reason_family[i]
                code = {
                    "feature": rng.choice(["feature_value_wrong", "stale_features",
                                           "feature_missing"]),
                    "model": rng.choice(["score_too_harsh", "score_too_soft",
                                         "unstable_vs_last_week"]),
                    "process": rng.choice(["policy_exception", "customer_goodwill",
                                           "missing_document"]),
                }[fam]
                decisions.append({
                    "claim_id": cid, "adjuster_id": adjuster,
                    "decision_datetime": dec_t,
                    "human_decision": "repairable" if row.truth_is_total_loss else "total_loss",
                    "reason_code_family": fam,
                    "reason_code": str(code),
                    "suspected_feature": ("vehicle_acv" if fam == "feature"
                                          and rng.random() < 0.6 else None),
                    # whether this override turned out to be wrong
                    "adjuster_was_wrong": bool(adj_wrong[i]),
                })

            # ---- outcome -----------------------------------------------------
            if row.truth_is_total_loss:
                tl_t = est_t + pd.Timedelta(days=float(rng.uniform(1, 12)))
                ev("TOTAL_LOSS_DECLARED", tl_t, {"acv": float(row.truth_acv)})
                salv = float(np.round(row.truth_acv * rng.uniform(0.12, 0.28), 0))
                ev("SALVAGE_VALUED", tl_t + pd.Timedelta(days=3), {"amount": salv})
                paid = float(np.round(row.truth_acv - 500, 0))
                pay_t = tl_t + pd.Timedelta(days=float(rng.uniform(5, 20)))
            else:
                paid = float(np.round(row.truth_repair_total - 500, 0))
                pay_t = est_t + pd.Timedelta(days=float(rng.uniform(6, 30)))

            ev("SETTLEMENT_PAID", pay_t, {"amount": paid})
            financials.append({"claim_id": cid, "txn_type": "PAYMENT",
                               "amount": paid, "txn_datetime": pay_t})

            # ---- subrogation: why the 365-day label differs from the 30-day one
            if do_subro[i]:
                rec_t = pay_t + pd.Timedelta(days=int(rng.integers(sub_lo, sub_hi)))
                rec = float(np.round(paid * rng.uniform(rec_lo, rec_hi), 0))
                ev("SUBROGATION_RECOVERED", rec_t, {"amount": rec})
                financials.append({"claim_id": cid, "txn_type": "RECOVERY",
                                   "amount": -rec, "txn_datetime": rec_t})

            ev("CLAIM_CLOSED", pay_t + pd.Timedelta(days=float(rng.uniform(1, 10))))

        ev_df = pd.DataFrame(events)
        ev_df["event_id"] = [f"EVT-{i:08d}" for i in range(1, len(ev_df) + 1)]
        ev_df = ev_df[["event_id", "claim_id", "event_type", "event_datetime", "payload"]]

        fin_df = pd.DataFrame(financials)
        fin_df["txn_id"] = [f"FIN-{i:08d}" for i in range(1, len(fin_df) + 1)]
        fin_df = fin_df[["txn_id", "claim_id", "txn_type", "amount", "txn_datetime"]]

        dec_df = pd.DataFrame(decisions)
        if len(dec_df):
            dec_df["decision_id"] = [f"DEC-{i:07d}" for i in range(1, len(dec_df) + 1)]

        return ev_df, fin_df, dec_df

    # ------------------------------------------------------------- labels
    def gen_labels(self, claims, financials) -> pd.DataFrame:
        """
        Outcome labels at several as-of dates.

        This is the table that makes the point. A claim's incurred amount at 30
        days, 90 days and 365 days are three different facts, and a model scored
        against the wrong one is being judged unfairly. Append-only, one row per
        (claim, label_type, as_of).
        """
        rows = []
        fin = financials.copy()
        fin["txn_datetime"] = pd.to_datetime(fin["txn_datetime"], utc=True)

        for horizon in (30, 90, 365):
            cutoff = claims["fnol_datetime"] + pd.Timedelta(days=horizon)
            cut = pd.DataFrame({"claim_id": claims["claim_id"].values,
                                "cutoff": pd.to_datetime(cutoff.values, utc=True)})
            j = fin.merge(cut, on="claim_id")
            j = j[j["txn_datetime"] <= j["cutoff"]]
            inc = (j[j["txn_type"].isin(["PAYMENT", "RECOVERY"])]
                   .groupby("claim_id")["amount"].sum())

            for cid, when in zip(claims["claim_id"], cutoff):
                # only emit if the horizon has actually elapsed by end_date —
                # the simulated "now". A later cutoff means that label does not
                # exist yet in this dataset's timeline.
                if when > self.end:
                    continue
                rows.append({
                    "claim_id": cid,
                    "label_type": "incurred_net",
                    "label_value": float(inc.get(cid, 0.0)),
                    "label_as_of_date": when.normalize(),
                    "label_maturity_days": horizon,
                    "is_final": horizon == 365,
                })

        # the total-loss label: arrives when declared, not at FNOL
        for r in claims.itertuples(index=False):
            tl_as_of = pd.Timestamp(r.fnol_datetime) + pd.Timedelta(days=45)
            if tl_as_of > self.end:
                continue
            rows.append({
                "claim_id": r.claim_id,
                "label_type": "total_loss",
                "label_value": float(bool(r.truth_is_total_loss)),
                "label_as_of_date": tl_as_of.normalize(),
                "label_maturity_days": 45,
                "is_final": True,
            })

        df = pd.DataFrame(rows)
        df["outcome_id"] = [f"OUT-{i:08d}" for i in range(1, len(df) + 1)]
        return df[["outcome_id", "claim_id", "label_type", "label_value",
                   "label_as_of_date", "label_maturity_days", "is_final"]]

    # --------------------------------------------------------------- run
    def run(self) -> dict[str, pd.DataFrame]:
        t = self.tables
        print("  customers ...", end="", flush=True)
        t["customer"] = self.gen_customers(); print(f" {len(t['customer']):,}")

        print("  policies ...", end="", flush=True)
        t["policy"] = self.gen_policies(t["customer"]); print(f" {len(t['policy']):,}")

        print("  vehicles ...", end="", flush=True)
        t["vehicle"] = self.gen_vehicles(t["policy"]); print(f" {len(t['vehicle']):,}")

        print("  salvage market ...", end="", flush=True)
        t["salvage_market"] = self.gen_salvage_market(); print(f" {len(t['salvage_market']):,}")

        print("  claims ...", end="", flush=True)
        claims = self.gen_claims(t["customer"], t["policy"], t["vehicle"],
                                 t["salvage_market"])
        print(f" {len(claims):,}")

        print("  valuations ...", end="", flush=True)
        t["vehicle_valuation"] = self.gen_valuations(t["vehicle"], claims)
        print(f" {len(t['vehicle_valuation']):,}")

        print("  lifecycle ...", end="", flush=True)
        ev, fin, dec = self.gen_lifecycle(claims)
        t["claim_event"] = ev
        t["claim_financial"] = fin
        t["adjuster_decision"] = dec
        print(f" {len(ev):,} events, {len(fin):,} txns, {len(dec):,} decisions")

        print("  labels ...", end="", flush=True)
        t["outcome_label"] = self.gen_labels(claims, fin)
        print(f" {len(t['outcome_label']):,}")

        # strip the underscore-prefixed ground truth from the shipped claim table
        t["claim"] = claims[[c for c in claims.columns if not c.startswith("truth_")]]
        t["claim_truth"] = claims[["claim_id"] +
                                  [c for c in claims.columns if c.startswith("truth_")]]
        return t


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

def summarise(t: dict, gen: Generator) -> None:
    claims = t["claim"]
    truth = t["claim_truth"]
    m = claims.merge(truth, on="claim_id")
    coll = m[m["cause_of_loss"] == "collision"]

    print("\n" + "=" * 62)
    print("SANITY CHECK")
    print("=" * 62)
    print(f"  total loss rate, collision claims : {coll['truth_is_total_loss'].mean():6.1%}")
    print(f"  total loss rate, all claims       : {m['truth_is_total_loss'].mean():6.1%}")
    print(f"  mean ACV at loss                  : ${m['truth_acv'].mean():>10,.0f}")
    print(f"  mean repair total                 : ${m['truth_repair_total'].mean():>10,.0f}")
    print(f"  mileage missing                   : {t['vehicle']['mileage_est'].isna().mean():6.1%}")

    ch = gen.cfg["tlt_change"]
    if ch["enabled"]:
        eff = pd.Timestamp(ch["effective_date"], tz="UTC")
        # measure on the population the change actually touches: collision
        # claims in that state. Averaging over all causes dilutes it to noise.
        st = m[(m["state"] == ch["state"]) & (m["cause_of_loss"] == "collision")]
        pre = st[st["loss_datetime"] < eff]
        post = st[st["loss_datetime"] >= eff]
        print(f"\n  CONCEPT DRIFT — {ch['state']} statutory threshold "
              f"{gen.cfg['states'][ch['state']]['tlt']} -> {ch['new_tlt']} "
              f"on {ch['effective_date']}")
        print(f"    collision total loss rate BEFORE : {pre['truth_is_total_loss'].mean():6.1%}"
              f"   (n={len(pre):,})")
        print(f"    collision total loss rate AFTER  : {post['truth_is_total_loss'].mean():6.1%}"
              f"   (n={len(post):,})")
        print("    input features are unchanged. This is P(Y|X) moving —")
        print("    a feature-drift monitor sees nothing.")

    n_stale = len(getattr(gen, "_stale_claims", []))
    print(f"\n  STALE VALUATIONS — {n_stale:,} claims scored on an understated ACV")
    if n_stale:
        val = t["vehicle_valuation"]
        sv = val[val["source"] == "vendor_feed_stale"][["vehicle_id", "acv"]]
        sv = sv.rename(columns={"acv": "acv_served"})
        cand = m[m["claim_id"].isin(gen._stale_claims)].merge(sv, on="vehicle_id")
        served = cand["truth_repair_total"] / cand["acv_served"]
        true_r = cand["truth_repair_total"] / cand["truth_acv"]
        flip = cand[(served >= cand["truth_tlt"]) != (true_r >= cand["truth_tlt"])]
        print(f"    of those, {len(flip):,} would have the total-loss decision FLIP")
        print("    on the stale value. These are the root-cause demo claims:")
        for cid in flip["claim_id"].head(5):
            print(f"      {cid}")

    dec = t["adjuster_decision"]
    if len(dec):
        print(f"\n  ADJUSTER OVERRIDES — {len(dec):,} "
              f"({len(dec)/len(claims):.1%} of claims)")
        print("    by attributed cause:")
        for fam, cnt in dec["reason_code_family"].value_counts().items():
            print(f"      {fam:<9} {cnt:>6,}  ({cnt/len(dec):5.1%})")
        print(f"    overrides that were themselves wrong: "
              f"{dec['adjuster_was_wrong'].mean():.1%}")

    lab = t["outcome_label"]
    inc = lab[lab["label_type"] == "incurred_net"]
    print("\n  LABEL MATURITY — mean net incurred by horizon:")
    for h, v in inc.groupby("label_maturity_days")["label_value"].mean().items():
        print(f"      {h:>4}d : ${v:>10,.0f}")
    print("    incurred RISES from 30d to 90d as settlements land,")
    print("    then FALLS by 365d as subrogation recoveries come in.")
    print("    Same claim, three different truths. Score a model against")
    print("    the wrong one and you are judging it unfairly.")
    print("=" * 62 + "\n")


def write(t: dict, outdir: Path, fmt: str) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    for name, df in t.items():
        if fmt in ("parquet", "both"):
            df.to_parquet(outdir / f"{name}.parquet", index=False)
        if fmt in ("csv", "both"):
            df.to_csv(outdir / f"{name}.csv", index=False)
    total = sum(f.stat().st_size for f in outdir.glob("*"))
    print(f"wrote {len(t)} tables to {outdir}/  ({total/1e6:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default=None, help="override output.dir")
    ap.add_argument("--format", default=None, choices=["parquet", "csv", "both"])
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    outdir = Path(args.out or cfg["output"]["dir"])
    fmt = args.format or cfg["output"]["format"]

    print(f"generating (seed={cfg['seed']}) ...")
    gen = Generator(cfg)
    tables = gen.run()
    summarise(tables, gen)
    write(tables, outdir, fmt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
