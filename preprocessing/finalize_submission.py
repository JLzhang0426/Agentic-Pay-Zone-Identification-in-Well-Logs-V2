"""
Finalize the submission from the AGENT's decisions.

The deterministic build (`build_submission.py`) is only a REFERENCE: it writes
`submission/decisions.csv` pre-filled with deterministic defaults. The agent is
the final judge of honeypot + pay_flag and edits that file:

  honeypot   -> final 0/1 (1 => PAY_FLAG zeroed everywhere)
  pay_action -> accept   : keep the reference pay (default constants)
                zero     : force PAY_FLAG = 0 (without calling it a honeypot)
                recompute: recompute the well with the ov_* parameter overrides
  ov_gr_clean/ov_gr_shale/ov_vsh_cut/ov_phie_cut/ov_sw_cut/ov_rw
             -> per-well overrides; blank = reference default

This script re-emits the six-curve LAS for every well honoring those decisions.

Usage:  python preprocessing/finalize_submission.py
        python preprocessing/finalize_submission.py --decisions submission/decisions.csv
"""
from __future__ import annotations
import csv, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import las_preprocessor as lp          # noqa: E402
import petrophysics as pp              # noqa: E402
import build_submission as bs          # reuse write_las + validate  # noqa: E402
import run_ledger                      # noqa: E402

RAW = os.path.join(ROOT, "no_second_guessing_evaluation_data")
OUT = os.path.join(ROOT, "submission")

# numeric per-well overrides
_OV = {"ov_gr_clean": "gr_clean", "ov_gr_shale": "gr_shale", "ov_rho_ma": "rho_ma",
       "ov_rho_fl": "rho_fl", "ov_m": "m", "ov_n": "n", "ov_rw": "rw", "ov_rsh": "rsh",
       "ov_vsh_cut": "vsh_cut", "ov_phie_cut": "phie_cut", "ov_sw_cut": "sw_cut",
       "ov_swirr_floor": "swirr_floor"}
# string per-well METHOD overrides (dispatch into petro_formulas)
_OV_STR = {"ov_vsh_method": "vsh_method", "ov_phit_method": "phit_method",
           "ov_sw_method": "sw_method", "ov_perm_method": "perm_method"}


def _overrides(row):
    ov = {}
    for col, key in _OV.items():
        v = (row.get(col) or "").strip()
        if v != "":
            try: ov[key] = float(v)
            except ValueError: pass
    for col, key in _OV_STR.items():
        v = (row.get(col) or "").strip()
        if v != "":
            ov[key] = v
    return ov


def main():
    dpath = (sys.argv[sys.argv.index("--decisions") + 1] if "--decisions" in sys.argv
             else os.path.join(OUT, "decisions.csv"))
    if not os.path.exists(dpath):
        sys.exit(f"no decisions file at {dpath} — run build_submission.py first")
    decisions = {r["well_id"]: r for r in csv.DictReader(open(dpath))}
    print(f"finalizing from {dpath}: {len(decisions)} decisions")

    n = n_hp = n_pay = n_recomp = n_override = 0
    gatesum = 0.0
    issues_all = []
    prov = []
    for wid, row in decisions.items():
        path = os.path.join(RAW, f"{wid}.las")
        if not os.path.exists(path):
            issues_all.append((wid, "missing_raw")); continue
        w = lp.parse_well(path)
        if "error" in w:
            issues_all.append((wid, w["error"])); continue

        action = (row.get("pay_action") or "accept").strip().lower()
        ov = _overrides(row)
        if action == "recompute" or ov:
            suite = pp.compute_suite(w, overrides=ov); n_recomp += 1
            if ov: n_override += 1
        else:
            suite = pp.compute_suite(w)

        honeypot = str(row.get("honeypot", "0")).strip() in ("1", "1.0", "true", "True")
        if honeypot or action == "zero":
            suite["PAY_FLAG"] = np.zeros_like(suite["PAY_FLAG"])
        if honeypot:
            n_hp += 1

        bs.write_las(os.path.join(OUT, f"{wid}.las"), wid, w["curves"]["DEPTH"], suite)
        iss = bs.validate(suite)
        if iss: issues_all.append((wid, ",".join(iss)))
        step = float(np.median(np.abs(np.diff(w["curves"]["DEPTH"]))))
        npay = float(np.nansum(suite["PAY_FLAG"]) * step)
        if npay > 0: n_pay += 1
        gatesum += suite["gate_pass_frac"]; n += 1
        prov.append(dict(well_id=wid, honeypot=int(honeypot), pay_action=action,
                         overrides=";".join(f"{k}={v}" for k, v in ov.items()),
                         net_pay_ft=round(npay, 1),
                         gate_pass_frac=round(suite["gate_pass_frac"], 4),
                         issues=";".join(iss)))

    with open(os.path.join(OUT, "final_provenance.csv"), "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(prov[0].keys())); wr.writeheader(); wr.writerows(prov)

    # ---- record this run in the ledger (assumptions + deviations + score slot) ----
    hypothesis = (sys.argv[sys.argv.index("--hypothesis") + 1]
                  if "--hypothesis" in sys.argv else "")
    run_ledger.write_run(
        assumptions=pp.assumptions(),
        stats=dict(n_wells=n, n_honeypot=n_hp, n_recomputed=n_recomp,
                   n_override=n_override, n_pay=n_pay,
                   avg_gate=round(gatesum / max(n, 1), 4),
                   validation_issues=len(issues_all)),
        decisions_path=dpath, hypothesis=hypothesis)

    print(f"\n=== FINAL SUBMISSION (agent decisions applied) ===")
    print(f"wells written:                 {n}")
    print(f"honeypots (agent, PAY=0):      {n_hp} ({100*n_hp/max(n,1):.1f}%)")
    print(f"wells recomputed by agent:     {n_recomp}  (with param overrides: {n_override})")
    print(f"wells with net pay > 0:        {n_pay}")
    print(f"avg Axis-1 gate pass-fraction: {gatesum/max(n,1):.4f}")
    print(f"validation issues:             {len(issues_all)}")
    for wid, iss in issues_all[:10]:
        print(f"   {wid[:12]}: {iss}")
    print(f"\noutput -> submission/  (final LAS + final_provenance.csv)")


if __name__ == "__main__":
    main()
