---
name: workflow
description: Orchestrator for the No-Second-Guessing pay-zone challenge. Three-stage agentic pipeline (per-well expert analysis -> honeypot detection -> emit) where the two domain SKILLs ARE the learnable model, refined one A/B at a time against the leaderboard. Load this first.
---

# No Second Guessing — Workflow & Learning Loop

This is the **orchestrator**. The actual intelligence lives in two sibling skills
that are treated as a **model we train by editing**:
- [`well-log-analysis`](../well-log-analysis/SKILL.md) — a senior petrophysicist
  who analyzes **one well at a time** from its raw LAS and makes that well's own
  assumptions (curve picks, endpoints, Rw, cutoffs) to compute VSH/PHIT/PHIE/SW/
  PERM/PAY_FLAG. **Does NOT decide honeypots.**
- [`honeypot-detection`](../honeypot-detection/SKILL.md) — runs **after** every
  well is computed, looks across **all 800 wells + their results**, and flags the
  ~25% honeypots (baked-in physics violations) whose pay must be zeroed.

## Core principle — the skills are the model
We do not hand-tune global constants well-by-well in code. Instead the
**petrophysicist's reasoning is encoded in the two domain skills**, and each
iteration we **update or A/B one thing in a skill** — exactly like a petrophysicist
revising their interpretation method — and let the **leaderboard score say whether
the edit helped**. The run ledger (`runs/`) is the training log.

## Architecture (3 stages)
```
Stage 0  (deterministic, code) parse + resolve every raw LAS
         preprocessing/run_pipeline.py -> processed/wells/<id>.csv, well_features.csv
Stage 1  (agentic, PER WELL)   each well analyzed individually by an agent acting
         as a senior petrophysicist via well-log-analysis SKILL -> per-well
         assumptions + the six curves. NO honeypot decision here.
Stage 2  (agentic, GLOBAL)     honeypot-detection SKILL ranks all 800 wells by
         physics-violation evidence (agents + formulas) -> zero pay on honeypots.
Stage 3  (code) emit six-curve LAS per well, validate gates, package.
         preprocessing/build_submission.py / finalize_submission.py
```
Stage 1 is deliberately **per-well and honeypot-blind**: a well is interpreted on
its own merits. Honeypot rejection is a **separate, later, cross-well** judgment so
it can use the full population and the computed results.

## Subagent orchestration — parallelize per-well work
The 800 wells are independent interpretations, so run them in **parallel** via
subagents. This both enforces the per-well discipline (each well judged on its own
merits, thoroughly) and scales throughput across 800 wells.

**Stage 1 — per-well analysis (fan out).** Dispatch subagents, each owning a
**non-overlapping slice** of wells (e.g. ~30–40 wells/agent, ~20 agents). Each
subagent loads the `well-log-analysis` skill and, **for every well in its slice**,
runs the full loop — *read the whole log → assume → compute → critique the result →
revise → recompute, iterating until the well is thorough* — then writes that well's
`ov_*` row to a batch file. One well is never split across agents. The lead **merges**
the batch files into `decisions.csv` and validates (schema, coverage, gates) before
finalizing. Pilot 1–2 agents first to confirm the output contract, then fan out.

**Stage 2 — honeypot detection (fan out, then reconcile globally).** After all wells
are computed, dispatch subagents over batches: each reads the **full logs + results**
for its batch, applies the `honeypot-detection` skill (catch-don't-rescue), and
returns a 0/1 call **plus an honest 0–1 conviction** per well. The lead then
**reconciles globally** — rank all 800 by conviction (blended with the deterministic
`honeypot_score`) and cut at ~25% — so independent batches never drift the rate.
**Do not impose a per-batch quota**; a slice may honestly hold more or fewer
honeypots than 25%.

**Lead responsibilities:** dispatch slices, merge batch outputs, do the global
honeypot reconciliation, validate, finalize, record the score, and choose the next
A/B. Keep batch I/O as files (one row per well) so nothing depends on parsing long
agent messages.

## The compute substrate (code the skills drive — keep, don't re-tune by hand)
| File | Role |
|---|---|
| `preprocessing/las_preprocessor.py` | Stage 0 parse + canonical curve resolver |
| `preprocessing/run_pipeline.py` | builds `processed/wells/`, `well_features.csv` |
| `preprocessing/petro_formulas.py` | pure formula TOOLBOX (every VSH/PHIT/PHIE/SW/PERM/Rw/pay method) the agent picks from |
| `preprocessing/petrophysics.py` | neutral `compute_suite(w, overrides=...)` engine + gates + honeypot_score (no baked-in interpretation) |
| `preprocessing/build_submission.py` | deterministic reference build + `decisions.csv` |
| `preprocessing/merge_overrides.py` | lead's glue: merge subagent batch files into `decisions.csv` (Stage-1 ov_*; Stage-2 honeypot, with `--reconcile` for the global ~25% cut) |
| `preprocessing/finalize_submission.py` | apply per-well decisions -> final LAS + ledger |
| `preprocessing/run_ledger.py` | per-run assumptions + score feedback |
| `submission/decisions.csv` | the control surface: per-well `ov_*` assumptions + honeypot flag |
| `runs/scoreboard.csv` | A/B history: assumptions vs score per run (the training log) |

The agent's control surface per well is `submission/decisions.csv`: Stage-1 agents
write per-well `ov_*` assumptions — params (`ov_gr_clean/ov_gr_shale/ov_rho_ma/
ov_rho_fl/ov_m/ov_n/ov_rw/ov_rsh/ov_vsh_cut/ov_phie_cut/ov_sw_cut/ov_swirr_floor`)
and method picks (`ov_vsh_method/ov_phit_method/ov_sw_method/ov_perm_method`);
Stage-2 agents write `honeypot` (0/1). `finalize_submission.py` recomputes each well
with its overrides and zeroes honeypot pay. The engine bakes in no interpretation —
blank fields fall back to neutral defaults, so the agent (skill) is the authority.

## Scoring (geometric mean of 4 axes; see docs/challenge.md)
`S = (A1·A2·A3·A4)^(1/4)`. A1 physics gates · A2 pay footage+Jaccard (real wells) ·
A3 honeypot rejection (**quadratic** — missing honeypots is very costly) · A4
PHIE/SW/PERM RMSE in true pay. A zero on any axis zeros everything.

## The learning loop (do this every iteration)
1. Pick **one** edit to a domain skill (a sharpened assumption rule), tag the
   hypothesis.
2. Run Stage 1 -> Stage 2 -> emit. `finalize_submission.py --hypothesis "..."`
   writes the run manifest + a blank scoreboard row.
3. Submit. Record the score:
   `python preprocessing/run_ledger.py record <run_id> --public S [--a1 .. --a4 ..]`
4. Read `runs/scoreboard.csv` `delta_vs_prev`. Keep the edit if it helped, revert
   if it hurt. **One skill edit per run** so every score delta is attributable
   (70-submission budget).

## Status & where knowledge lives — policy vs log (don't mix them)
- **The append-only LOG of every A/B** is `runs/scoreboard.csv` (+ each run's
  `runs/<id>/manifest.json` assumptions snapshot), written by `run_ledger.py`. This
  is the single home for *all per-loop feedback* — every hypothesis, score, delta,
  outcome. **Do not paste raw findings into any skill**: a skill is a *policy*, and
  accumulating history in it makes it bloat and self-contradict over reverted runs.
- **The distilled current-best RULES** live in the **domain skill where the acting
  agent reads them**. When an A/B *confirms* a lesson, edit that rule there (revert
  there if it hurts). Each lesson lives where it acts:
  - percent-Timur PERM, tight-SW-cutoff, Rw≈0.05, conservative per-well tuning
    → [`well-log-analysis`](../well-log-analysis/SKILL.md)
  - catch-don't-rescue, the ~25% global rate → [`honeypot-detection`](../honeypot-detection/SKILL.md)

Current trajectory (public): 23.76 base → 22.30 (honeypot *rescues*, WORSE) → 23.84
(PERM fix) → 25.19 (SW 0.50) → **26.29 (SW 0.45, best)** → SW 0.40 pending. Best
config: percent-Timur PERM · SW_cut 0.45 · Rw 0.05 · 204 honeypots. Full per-run
detail and the next-lever cues are in `runs/scoreboard.csv` — read it, don't
duplicate it here.

## When to use
Load this skill to orchestrate a run or to decide the next A/B. Then load
`well-log-analysis` (Stage 1) and `honeypot-detection` (Stage 2).
