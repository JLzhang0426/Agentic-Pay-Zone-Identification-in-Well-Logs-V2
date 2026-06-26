"""
Merge subagent batch outputs into submission/decisions.csv — the lead's glue for
both Stage 1 (per-well assumptions) and Stage 2 (honeypot detection). Pure plumbing:
it applies whatever the agents decided; it makes NO petrophysical assumption itself.

Batch files are CSVs (one row per well) with `well_id` plus any subset of the
decisions columns the agents filled:
  Stage 1: any of the ov_* params/methods (+ optional `notes`).
  Stage 2: `honeypot` (0/1) and optional `hp_conf` (0-1 conviction).

Behaviour:
  - ov_* present  -> written through; `pay_action` set to recompute.
  - honeypot col  -> applied as given, UNLESS --reconcile: then rank ALL wells by a
    blended conviction (0.5*norm(honeypot_score) + 0.5*hp_conf) and flag the top
    --target-frac (default 0.25); honest per-well convictions, no per-batch quota.

Usage:
  python preprocessing/merge_overrides.py --batches "processed/stage1/*.csv"
  python preprocessing/merge_overrides.py --batches "processed/hp/*.csv" --reconcile [--target-frac 0.25]
  (add --dry-run to preview)
"""
from __future__ import annotations
import csv, glob, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEC = os.path.join(ROOT, "submission", "decisions.csv")

OV_PARAM = ["ov_gr_clean", "ov_gr_shale", "ov_rho_ma", "ov_rho_fl", "ov_m", "ov_n",
            "ov_rw", "ov_rsh", "ov_vsh_cut", "ov_phie_cut", "ov_sw_cut", "ov_swirr_floor"]
OV_METHOD = ["ov_vsh_method", "ov_phit_method", "ov_sw_method", "ov_perm_method"]
OV_ALL = OV_PARAM + OV_METHOD


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    if not os.path.exists(DEC):
        sys.exit("no submission/decisions.csv — run build_submission.py first")
    ref = list(csv.DictReader(open(DEC)))
    cols = list(ref[0].keys())
    by_id = {r["well_id"]: r for r in ref}

    pattern = _arg("--batches")
    if not pattern:
        sys.exit("--batches GLOB required")
    files = sorted(glob.glob(os.path.join(ROOT, pattern)) if not os.path.isabs(pattern) else glob.glob(pattern))
    batch = {}
    for fp in files:
        for r in csv.DictReader(open(fp)):
            wid = (r.get("well_id") or "").strip()
            if wid:
                batch[wid] = r
    print(f"loaded {len(batch)} well rows from {len(files)} batch files")

    reconcile = "--reconcile" in sys.argv
    n_ov = n_hp = 0

    # ---- Stage-1 style: apply ov_* overrides ----
    for wid, r in batch.items():
        row = by_id.get(wid)
        if row is None:
            continue
        set_any = False
        for c in OV_ALL:
            v = (r.get(c) or "").strip()
            if v and c in cols:
                row[c] = v; set_any = True
        if set_any:
            n_ov += 1
            if (row.get("pay_action") or "accept").strip().lower() == "accept":
                row["pay_action"] = "recompute"
            note = (r.get("notes") or "").replace(",", ";").strip()
            if note:
                row["notes"] = note[:160]

    # ---- Stage-2 style: honeypot ----
    has_hp = any((r.get("honeypot") or "").strip() != "" for r in batch.values())
    if has_hp:
        if reconcile:
            tfrac = float(_arg("--target-frac", "0.25"))
            scores = np.array([float(by_id[w]["honeypot_score"] or 0) for w in by_id])
            smax = max(0.6, float(scores.max()) if scores.size else 0.6)
            conv = {}
            for wid, row in by_id.items():
                b = batch.get(wid, {})
                hpc = (b.get("hp_conf") or "").strip()
                try: hpc = float(hpc)
                except ValueError:
                    hpc = 1.0 if str(b.get("honeypot", "")).strip() in ("1", "1.0") else 0.0
                det = float(row["honeypot_score"] or 0) / smax
                conv[wid] = 0.5 * min(det, 1.0) + 0.5 * min(max(hpc, 0.0), 1.0)
            n_target = int(round(tfrac * len(by_id)))
            flagged = set(sorted(conv, key=lambda w: -conv[w])[:n_target])
            for wid, row in by_id.items():
                row["honeypot"] = 1 if wid in flagged else 0
            n_hp = len(flagged)
            print(f"honeypot RECONCILED globally: flagged {n_hp} (~{100*n_hp/len(by_id):.1f}%, target {tfrac:.0%})")
        else:
            for wid, r in batch.items():
                row = by_id.get(wid)
                if row is not None and (r.get("honeypot") or "").strip() != "":
                    row["honeypot"] = 1 if str(r["honeypot"]).strip() in ("1", "1.0") else 0
            n_hp = sum(1 for row in by_id.values() if str(row.get("honeypot")) in ("1", "1.0"))
            print(f"honeypot calls applied as-is: {n_hp} flagged")

    print(f"wells with >=1 ov_* override: {n_ov}")
    if "--dry-run" in sys.argv:
        print("[dry-run] not writing"); return
    with open(DEC, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        wr.writeheader(); wr.writerows(ref)
    print(f"wrote {DEC} -> run finalize_submission.py")


if __name__ == "__main__":
    main()
