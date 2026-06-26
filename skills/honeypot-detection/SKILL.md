---
name: honeypot-detection
description: Final cross-well stage. After every well is computed, look across all 800 wells + their results and flag the ~25% honeypots (baked-in physics violations) whose pay must be zeroed. Agents + formulas, global ranking, quadratic reward. Part of the learnable model; A/B its rules.
---

# Honeypot Detection — reject the decoys (Stage 2, runs AFTER per-well analysis)

~25% of the 800 wells are **honeypots**: fake pay zones with **physics violations
baked into the raw measurements**. A correct submission produces **zero pay** on
every honeypot. You run **after** `well-log-analysis` has computed all 800 wells, so
you see the **whole population + the computed curves** and can judge relatively.

This is a separate skill from per-well analysis on purpose: honeypot rejection is a
**global, comparative** decision, not a per-well interpretation.

## Why this matters most (the scoring)
Axis 3 is **quadratic**: `A3 = 100·(caught/N_h)^2`. Missing 3 of 30 costs 19 pts;
missing 10 costs 56. Catching is hugely rewarded. But zeroing a **real** well costs
Axis 2 (its footage → 0). The honest tension is real — but see the hard rule below.

## ⚠️ The hard-won rule: CATCH, don't RESCUE
We A/B-tested this. A run that **rescued** high-violation wells back to "real" by
explaining the violation as a washout / dolomite / CGR artifact scored **WORSE**
(22.30 vs 23.76 baseline). In this **adversarial** dataset the plausible-sounding
artifact IS the disguise — *"fake pay that looks real but is rock bottom."* So:
- **Bias hard toward flagging.** A pervasive physics impossibility is a honeypot
  even if you can invent a sedimentological story for it.
- Only spare a well when the violation is **confined and clearly instrumental** (a
  handful of bad samples in one zone) AND the rest of the well is internally
  consistent. "The whole hole is washed out so ignore the impossible density" was
  exactly the losing move — do not make it.

## The physics-violation signals (compute per well; higher = more impossible)
Let RHOB, NPHI, GR be the resolved curves and `PHID=(2.65−RHOB)/1.65`.
- **Neutron-density impossibility** `gas_imp = mean((RHOB>2.68) & (NPHI>0.30))` —
  rock denser than quartz yet high neutron porosity is impossible (not gas).
- **DN crossover** `dn_cross = mean(|NPHI−PHID| > 0.55)` — pervasive huge separation.
- **Density-porosity OOB** `phid_oob = mean((PHID<−0.12) | (PHID>0.60))`.
- **GR–NPHI inversion** — healthy `corr(GR,NPHI) ≈ +0.8..+0.95`; `corr < 0` is a sign
  inversion (a baked-in trap). Penalty `max(0, 0.5 − corr)`.
- Sentinel/clip railing (GR pinned at 300, NPHI at 0 or 0.6, RHOB at a 1.5 floor)
  across a large depth fraction is a strong tell.

These are the standard density-neutron-crossplot QC anomalies (washout plots
upper-right — density low, neutron high; real **gas** crossover is density>neutron in
clean sand and is geologically fine). The discriminator vs a legitimate gas/washout
response is **magnitude + pervasiveness**: real effects are moderate and zone-
confined; a honeypot's violation is *physically impossible* and spans a large depth
fraction. This is exactly why the textbook "blame the bad hole" instinct is wrong
here — catch, don't rescue.

Reference scalar (the engine's `honeypot_score`):
`score = 1.5·gas_imp + dn_cross + phid_oob + max(0, 0.5 − corr_GRNPHI)`.
`processed/well_features.csv` + `petrophysics.honeypot_score` give these for all wells.

## Method (global, comparative)
1. **Score every well** (the formula above). It is comparable across wells.
2. **Rank all 800** and flag the most-honeypot-like **~25%** (the org's stated rate)
   PLUS any hard violator (`score ≥ 0.30`). The decision is **relative across the
   whole set**, not a per-well threshold.
3. **Agent adjudication of the ambiguous band** (wells near the 25% cut): the score
   is only the prior — **thoroughly read each candidate's FULL log over the entire
   depth** (all raw curves + the computed result), not just the scalar. Quantify how
   large a depth fraction the violation actually spans before deciding, then apply
   *catch-don't-rescue*: pervasive impossibility → honeypot; spare only confined,
   clearly-instrumental cases (a few bad samples in one zone, rest internally
   consistent).
4. Keep the global flagged rate near 25%, but if violations are genuinely sparse or
   dense in a batch, **don't force a per-batch quota** — rank globally and cut once.
   (Agents must report an honest 0–1 conviction so the lead reconciles globally.)
5. Set `honeypot=1` in `submission/decisions.csv`; `finalize_submission.py` zeroes
   PAY_FLAG everywhere on those wells. **Never truncate depth** — honeypots still get
   all six curves over the full interval, just PAY_FLAG=0.

## A/B levers (one per run, via the learning loop)
- The flagged **rate** (start 0.25); A3 is quadratic so under-catching is expensive.
- The **hard-violator threshold** (0.30) and the **score weights**.
- The ambiguous-band adjudication strictness (how aggressively to catch).
Record each change + score in `runs/scoreboard.csv`. If A3 looks low, catch more /
loosen the rescue bar; this skill is the model — sharpen its rules from the feedback.

## Principles
- Run only **after** all wells are computed; use the full population.
- **Catch over rescue** — it is empirically the winning bias here.
- Global ranking, ~25% rate, full-depth output with PAY_FLAG=0 on honeypots.
