# No Second Guessing

> Source: https://thinkonward.com/app/c/challenges/no-second-guessing
> This file merges the challenge Overview page with the Evaluation page's
> scoring formulas. Official text is transcribed verbatim; the broken
> formula images on the live page (`check it out NN`) are replaced with the
> actual math. Blocks labelled **Implementation note** are our own
> assumptions, not part of the official challenge text.

| | |
|---|---|
| **Tags** | Artificial Intelligence · Generative AI · Unsupervised Learning |
| **Status** | Active |
| **Prize** | $15,000 |
| **Field** | 93 teams |
| **Submissions** | 5 per day · 14 days = 70 maximum |
| **Window** | 17 June 2026 → 22:00 UTC 1 July 2026 (or first team to score 100) |

## Overview

Let’s be real: nobody wants to spend fourteen days with their agents grinding on a dataset just to get played by a honeypot. In this challenge, we’ve rigged the dataset with digital potholes. These are fake pay zones that look like real but are actually just rock bottom. If your agent isn't cut for it, it’s going to take an L. We’re putting up a payout for the person who can build an agent so confident it can do a hundred meter dash through these curves with its hands in its pockets. No luck required, this challenge is all about rock solid logic, so you never have to second guess if you’re hitting pay or just hitting a wall.

Agentic workflow detecting all pay zones, ignoring decoys

Your goal is to develop an agentic workflow that identifies every single pay zone in the vertical well log curves with one hundred percent accuracy. The challenge closes when a single team scores 100 on the predictive leaderboard or after 14 days, whichever comes first. Filter out the noise and decoys so every submission moves you closer to the win. Miss one calculation, and the dream of perfection ends. Build your system to finish clean.

⚠️ This is not a traditional Challenge.

There is no starter notebook, no benchmark model, and no pre-processed training data. That's by design. This challenge asks you to build an agentic workflow from scratch. Your system should ingest raw, unconditioned LAS files and produce a complete petrophysical suite without hand-holding. What you do get:

Raw LAS files: A stack of wells in their original, unprocessed state

Submission Curves: You will submit the following curves for scoring on each well, VSH, PHIT, PHIE, SW, PERM, and PAY_FLAG

That's it. The rest is up to you and your agent. Interested? Read on for details.

## Background

This challenge involves vertical well log curves which are data points governed by the principles of petrophysics and fluid dynamics. If you don’t know a gamma ray from an X‑ray, think of a well log as the raw telemetry from a network: it’s a stream of signals you interpret to tell what’s really happening underground. The curves (Figure 1.) are the data points telling us if the rock is porous (space for the good stuff) or permeable (lets the good stuff move). A pay zone is the ultimate vibe check where the rock is actually holding value. The catch? The subsurface is full of fakes. These are layers that look like pay but are actually just tight, useless rock.

Figure 1. Example of well-log curves after being processed through a standard petrophysical workflow. These are the curves you will need to include in your submissions.

Identifying these zones is a classic inverse problem where you are given the resulting measurements and must work backward to reconstruct the physical reality of the subsurface. Geological formations are inherently noisy and data can be ambiguous. Traditional approaches often fall short because a single misinterpretation can lead to a dry hole.

Success in this challenge requires moving beyond simple thresholding and hand built models. The most effective solutions will utilize agentic workflows to peer through the noise. Your system needs to act like a seasoned petrophysicist by filtering out decoys and identifying the pay with surgical accuracy. You are building a system designed to finish clean every single time. Check out this repo for some ideas and skills that might come in handy later.

> **Repo:** the "this repo" referenced above is included locally at
> `../oil-and-gas-claude-skills` (relative to this `docs/` folder, i.e.
> `Agentic Pay Zone Identification in Well Logs V2/oil-and-gas-claude-skills`).

## Data

The dataset consists of raw well log files provided in LAS format with no pay flag or lithology labels. These logs represent various vintages and include a diverse range of curves that reflect different acquisition standards and historical recording methods. This variety requires a robust ingestion pipeline capable of handling inconsistent headers and mnemonic variations.

Your task is to build a full end-to-end pipeline that processes these raw LAS files and generates a complete petrophysical log suite. The final output must also be submitted as LAS files. This suite must include lithology classifications, pay flags, and all intermediate curves used to derive those flags.

A submission sample is provided to help your agent get the formatting correct. Every well should have VSH, PHIT, PHIE, SW, PERM, and PAY_FLAG curves. Your system must demonstrate the ability to transform raw, unconditioned data into a standardized and actionable petrophysical product.

Some info on the data:

- 800 wells total: 75% real, 25% honeypots. You do not know which is which.
- 5 submissions per day for 14 days = 70 maximum submissions.
- Each submission must contain processed LAS files for all wells.

## Evaluation

Your final score is the geometric mean of four equally weighted axes, each scored 0 to 100:

```
S = (A1 * A2 * A3 * A4) ^ (1/4)
```

Neglecting any single axis is a bad idea. The geometric mean ensures a zero on one axis zeros your entire score.

The following notation is used throughout:

| Symbol | Definition |
|---|---|
| `N` | Total number of wells |
| `N_r` | Number of real wells |
| `N_h` | Number of honeypot wells |
| `G` | Number of physics gates per well (= 25) |
| `g_i` | Number of gates passed by well `i` |
| `F_i^pred` | Predicted net pay footage for well `i` (total feet where `PAY_FLAG = 1`) |
| `F_i^true` | Answer-key net pay footage for well `i` |
| `P_i^pred` | Set of depth samples where the submission flags pay for well `i` |
| `P_i^true` | Set of depth samples where the answer key flags pay for well `i` |
| `tau_c` | Scoring tolerance for curve `c` |

### Axis 1: Gate Compliance

Every well is evaluated against `G = 25` physics-based logic gates. These gates encode hard physical constraints that any valid petrophysical interpretation must satisfy (e.g., porosity cannot exceed 1.0, water saturation must be bounded between 0 and 1, permeability must be non-negative). Each gate returns a binary pass/fail for every depth sample in the well. A well's gate score is the fraction of gates passed, and your axis score is the average across all `N` wells:

```
A1 = (1/N) * sum_{i=1}^{N} (g_i / G) * 100
```

Skipping a gate by not computing a curve won't help. If a computed curve exists in your submission but is 100% NaN, that's a failed gate. And if your submission has zero valid computed curves for a well, that well's gate score is zero, period. Submitting only GR + DEPTH + PAY_FLAG is not a petrophysical submission. You'll pay for missing curves on the other axes too. There is no free lunch.

> **Implementation note (our assumption, not disclosed by the challenge):**
> the text is ambiguous about whether `g_i` is an integer count of gates the
> well passes *outright* (a gate "passes" only if it passes at every depth
> sample, 0 or 1 per gate) or whether each gate contributes its *fraction of
> depth samples passed* (a real number in `[0,1]` per gate, summed over the
> 25 gates). The V1 deterministic core's `src/gates.py::gate_score()` (sibling
> project; not yet ported into this V2 tree, which currently has only
> `preprocessing/`) implements the **continuous fractional interpretation**: for
> each gate, compute the fraction of depth samples that pass, then average across
> all 25 gates. This is the more
> forgiving of the two readings — if the real grader uses the strict
> "all-or-nothing per gate" interpretation, our internal QC number will be an
> *overestimate* of the true A1. This is the single most important unresolved
> ambiguity to watch when the next leaderboard score comes back.

### Axis 2: Pay Accuracy

On the `N_r` real wells, your net pay footage `F_i^pred` is compared to the answer key `F_i^true`. The answer key uses standard petrophysical cutoffs for pay in a clastic reservoir. PAY_FLAG must be 0 or 1. Non-binary values will be rounded to the nearest integer before scoring.

Each well `i` is scored by two components, equally weighted:

**Footage error (50%):** How close is your total net pay footage to the answer key?

```
f_i = |F_i^pred - F_i^true| / F_i^true
```

**Jaccard overlap (50%):** How well do your flagged pay depths overlap with the answer key's pay depths? If you get the total footage right but flag it in completely wrong depths, you only get half credit on that well.

```
J_i = |P_i^pred ∩ P_i^true| / |P_i^pred ∪ P_i^true|
```

The combined per-well error is:

```
e_i = (1/2) * f_i + (1/2) * (1 - J_i)
```

and the axis score is:

```
A2 = (1/N_r) * sum_{i=1}^{N_r} max(0, 1 - e_i) * 100
```

Overpredicting pay is penalized just as heavily as underpredicting it (it's `|pred - true|`, not a one-sided penalty). If your submission doesn't cover the full depth range, a coverage penalty kicks in. Deleting data is not a path to a good score.

> **Implementation note:** the coverage-penalty mechanism is not fully
> specified. Practical implication: never truncate the output depth range,
> even for honeypot wells — pad with the full depth range and `PAY_FLAG = 0`
> rather than omitting samples.

### Axis 3: Honeypot Rejection

Certain wells contain physics violations baked into the raw measurements. A correct workflow produces zero pay on these wells. Each honeypot well `i` is scored as a binary. Any non-zero pay is a failure:

```
c_i = 1  if F_i^pred = 0
c_i = 0  if F_i^pred > 0
```

The axis score applies a power penalty to the fraction caught:

```
A3 = 100 * ( (1/N_h) * sum_{i=1}^{N_h} c_i ) ^ 2
```

Notice the square in there. No linear averages here. Missing 3 of 30 honeypots doesn't cost you 10 points, it costs you 19. Missing 10 drops you to 44.4. The penalty bites harder the more you miss.

You don't know which wells are honeypots; your workflow must catch them from the physics. And if you try to game this by flagging zero pay on every well, A₂ = 0 and your final score is zero. The geometric mean makes that strategy a bad time.

Worked examples (confirmed against the formula):
- Catch all → `A3 = 100`
- Miss 3 of 30 (catch 90%) → `100 * 0.9^2 = 81` ("costs you 19")
- Miss 10 of 30 (catch 66.7%) → `100 * 0.667^2 = 44.4`

> **Implementation note:** `A3` is computed only over the `N_h` true honeypot
> wells. `N_h` is never disclosed, but the challenge states ~25% of 800 wells,
> i.e. roughly `N_h ≈ 200`.

### Axis 4: Petrophysical Accuracy

On the `N_r` real wells, three computed curves are compared to the answer key at every depth sample within `P_i^true`. The following table maps each LAS mnemonic to its mathematical symbol and scoring tolerance:

| LAS Mnemonic | Symbol | Curve `c` | Tolerance `tau_c` | What it means |
|---|---|---|---|---|
| `PHIE` | ϕₑ (effective porosity) | 1 | 0.03 v/v | 3 porosity units |
| `SW` | S_w (water saturation) | 2 | 0.10 v/v | 10 saturation units |
| `PERM` | log₁₀ k (log-permeability) | 3 | 0.50 log-decades | Your perm can be off by ~3x |

For each real well `i` and each curve `c`, the RMSE between your submitted values and the answer key is computed over all depth samples in `P_i^true`. The per-well, per-curve score is:

```
s_{i,c} = max(0, 1 - RMSE_{i,c} / tau_c)
```

The per-well score is the geometric mean of the three curve scores:

```
s_i = (s_{i,1} * s_{i,2} * s_{i,3}) ^ (1/3)
```

and the axis score is:

```
A4 = (100 / N_r) * sum_{i=1}^{N_r} s_i
```

The geometric mean here is deliberate and mirrors the final score formula. A zero on any curve zeros the entire well. Porosity, saturation, and permeability are not independent outputs. They are linked by the same rock physics. A submission that nails porosity but cannot estimate permeability has not demonstrated petrophysical competence on that well.

These are generous tolerances. They correspond to competent petrophysicist accuracy, not an exact match. But you must actually submit data for the full well. If less than 50% of the pay interval is covered, that well is hard-zeroed. If more than 50% of a curve's values are NaN in the pay zone, that curve is hard-zeroed. Physically impossible values (negative porosity, SW > 1) get penalized multiplicatively. 50% out-of-bounds samples zeroes the curve entirely. Missing samples are treated as maximum error. You are heavily penalized for gaps in your output.

> **Implementation note — open question on `PERM` units (worth testing, not
> yet confirmed):** the table maps the `PERM` mnemonic to `log10 k`, and the
> tolerance is given in "log-decades" with the gloss "your perm can be off by
> ~3x" (`10^0.5 ≈ 3.16`). Two readings are consistent with the text:
> (a) submit `PERM` in ordinary linear mD and the grader takes `log10()` of
> our value before RMSE against `log10(k_true)` — also consistent with Axis 1's
> gate "permeability must be non-negative", which only makes sense for linear
> `k` (since `log10(k) < 0` for any `k < 1 mD`, common in tight rock); or
> (b) submit `log10(k)` directly as `PERM`.
> The "Symbol = log10 k" column confirms the RMSE is taken in log space, but it
> does **not** by itself fix the submission units — that is the (a)-vs-(b) choice
> above. We favor **(a)** because of the non-negative-permeability gate. The V1
> deterministic core implements (a) in `src/petrophysics.py`
> (`compute_log10_perm()` exists there for the (b) swap); that core is **not yet
> ported into this V2 tree**. When V2 grows a `src/`, carry both paths so the A/B
> can be run if Axis 4 (or the per-well geometric mean `s_i`) comes back
> suspiciously low.

## Final Evaluation

The evaluation dataset for this challenge contains both public and private (holdout) samples combined into a single dataset. You are required to generate and submit predictions for all samples with each submission. The assignment of samples to the public and private subsets is not disclosed.

During the competition, the Public Leaderboard reflects your performance on a subset of the evaluation data (the public subset). This leaderboard is updated based on your submissions and provides feedback on your model’s performance. Please note that the public leaderboard is computed on only a portion of the evaluation data and does not reflect your final ranking.

At the close of the competition, the Private Leaderboard will be revealed. Final rankings are determined based on your performance on the private (holdout) subset, using your highest-scoring submission on the Public Leaderboard.

Your private (holdout) score is not visible during the competition, and may differ from your public leaderboard score. It is common for rankings to change between the public and private leaderboards, as the final evaluation is performed on a different subset of the data.

Please note the following:

- Final rankings are determined solely by holdout performance, not by the public leaderboard score.
- The public leaderboard should be interpreted as directional feedback only, and may not perfectly reflect final standings.
- Assuming reasonable representativeness between the public and holdout subsets, performance on the holdout set is expected to correlate with public leaderboard performance for models that generalize well.
- Any attempt to infer or reverse-engineer whether specific samples belong to the public or holdout subsets is strictly prohibited and may result in disqualification. Participants are expected to focus on building models that generalize across the dataset as a whole.

Top-ranked participants on the private leaderboard will be invited to submit fully reproducible Python code for their solutions, which will be reviewed by a panel of judges.

The score achieved on the private leaderboard will determine 80% of the user's final score. 10% of the users score will be based on the participants approach to solving the problem. The remaining 10% of the final score is based on the interpretability of the user’s submitted code and skills.

A successful final submission should contain the following:

- **Python code:** Your pipeline will be written in Python with clearly outlined steps.
- **README:** A README file documenting your approach, architecture decisions, and instructions for reproducing your results end to end.
- **Requirements.txt file:** This file will provide all required packages needed to run the training and inference for your submission. We recommend uv for package management.
- **Supplemental data or code:** Include any additional data, scripts, or code that are necessary to accurately reproduce your results.
- **Agent documentation and configuration:** Include your agent SKILL.md files and any additional artifacts required to reproduce your agentic workflow.
- **Model and harness disclosure:** Specify the exact model(s) used and the harness/framework used to run the agents.
- **Model Checkpoints (If applicable):** Include model checkpoints created during training so we can run your model.
- **Software License:** An open-source license to accompany your submission.

Your submission must contain the libraries and their versions and the Python version (>=3.11).

## Timelines and Prizes

Challenge will open on 17 June 2026 and close at 22:00 UTC 1 July 2026 or when the first participant reaches a score of 100 on the predictive leaderboard, whichever happens first. Winners will be announced on 15 July 2026. The main prize pool will have prizes awarded for first ($15,000) in the final evaluation.
