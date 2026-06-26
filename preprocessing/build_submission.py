"""
Build the final submission for "No Second Guessing".

Stage 0 -> 3 with a GLOBAL honeypot step:
  Pass 1 — parse every raw LAS, compute the six curves, and score every well's
           physics-violation likelihood (honeypot_score).
  Select — rank all wells by score and mark the most honeypot-like ~25% (the
           challenge says 25% of the 800 are honeypots) PLUS any "hard" violators.
  Pass 2 — write one LAS per well (full depth, all six curves); honeypots get
           PAY_FLAG = 0 everywhere. Emit a provenance trail + validate gates.

Usage:
  python preprocessing/build_submission.py [--rw fixed|metadata]
                                           [--honeypot-frac 0.25] [--limit N]
Output:
  submission/<well_id>.las     the six curves you submit
  submission/provenance.csv    per-well audit (roles, Rw, honeypot rank, gates)
"""
from __future__ import annotations
import csv, glob, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import las_preprocessor as lp          # noqa: E402
import petrophysics as pp              # noqa: E402
import lasio                           # noqa: E402

RAW = os.path.join(ROOT, "no_second_guessing_evaluation_data")
OUT = os.path.join(ROOT, "submission")
os.makedirs(OUT, exist_ok=True)

CURVE_META = [
    ("VSH", "v/v", "Shale volume (linear GR)"),
    ("PHIT", "v/v", "Total porosity (density-neutron)"),
    ("PHIE", "v/v", "Effective porosity (shale-corrected)"),
    ("SW", "v/v", "Water saturation (Archie)"),
    ("PERM", "mD", "Permeability (Timur, linear mD)"),
    ("PAY_FLAG", "", "Net pay flag (1=pay)"),
]


def write_las(path, wid, depth, suite, null=-999.25):
    las = lasio.LASFile()
    step = float(np.median(np.abs(np.diff(depth)))) if depth.size > 1 else 0.5
    las.well["STRT"].value = float(depth[0])
    las.well["STOP"].value = float(depth[-1])
    las.well["STEP"].value = round(step, 4)
    las.well["NULL"].value = null
    las.well["WELL"].value = wid
    las.append_curve("DEPT", depth, unit="ft", descr="Depth")
    for mnem, unit, descr in CURVE_META:
        data = np.asarray(suite[mnem], float)
        if mnem == "PAY_FLAG":
            data = np.where(np.isfinite(data), np.round(data), 0.0)
        las.append_curve(mnem, data, unit=unit, descr=descr)
    las.write(path, version=2.0, fmt="%.5g")


def validate(suite) -> list[str]:
    issues = []
    f = lambda a: np.asarray(a, float)[np.isfinite(np.asarray(a, float))]
    for m in ("VSH", "PHIT", "PHIE", "SW", "PERM", "PAY_FLAG"):
        if not np.isfinite(np.asarray(suite[m], float)).any():
            issues.append(f"{m}_all_nan")
    if (f(suite["VSH"]) < -1e-6).any() or (f(suite["VSH"]) > 1 + 1e-6).any(): issues.append("VSH_oob")
    if (f(suite["PHIE"]) < -1e-6).any() or (f(suite["PHIE"]) > 1 + 1e-6).any(): issues.append("PHIE_oob")
    if (f(suite["SW"]) < -1e-6).any() or (f(suite["SW"]) > 1 + 1e-6).any(): issues.append("SW_oob")
    if (f(suite["PERM"]) < -1e-6).any(): issues.append("PERM_neg")
    ph = np.isfinite(suite["PHIE"]) & np.isfinite(suite["PHIT"])
    if (suite["PHIE"][ph] > suite["PHIT"][ph] + 1e-6).any(): issues.append("PHIE_gt_PHIT")
    return issues


def main():
    rw_mode = sys.argv[sys.argv.index("--rw") + 1] if "--rw" in sys.argv else "fixed"
    hp_frac = float(sys.argv[sys.argv.index("--honeypot-frac") + 1]) if "--honeypot-frac" in sys.argv else 0.25
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None

    files = sorted(glob.glob(os.path.join(RAW, "*.las")))

    # ---- PASS 1: compute every well, collect honeypot scores ----
    recs = []   # light record per well
    print(f"pass 1: computing {len(files)} wells...")
    for i, path in enumerate(files):
        w = lp.parse_well(path)
        if "error" in w:
            print("  ERR", w["well_id"], w["error"]); continue
        s = pp.compute_suite(w, rw_mode=rw_mode)
        recs.append(dict(
            wid=w["well_id"], depth=w["curves"]["DEPTH"],
            curves={k: s[k] for k in ("VSH", "PHIT", "PHIE", "SW", "PERM", "PAY_FLAG")},
            score=s["honeypot_score"], hard=s["honeypot_hard"],
            reason=s["honeypot_reason"], rw=s["rw_used"],
            gate=s["gate_pass_frac"], qc=";".join(w["qc_flags"]),
            prov=w["provenance"], net_pay=s["net_pay_ft"]))
        if limit and len(recs) >= limit:
            break
        if (i + 1) % 100 == 0:
            print(f"  computed {i+1}/{len(files)}")

    # ---- GLOBAL HONEYPOT SELECTION: most-honeypot-like ~hp_frac, ∪ hard ----
    scores = np.array([r["score"] for r in recs])
    n_target = int(round(hp_frac * len(recs)))
    # rank-based threshold = score of the n_target-th highest well
    order = np.argsort(-scores)
    thresh = scores[order[n_target - 1]] if 0 < n_target <= len(recs) else np.inf
    AMB_BAND = 0.05   # wells within +-band of the cut, not hard -> agent reviews
    for r in recs:
        r["honeypot"] = bool(r["score"] >= thresh or r["hard"])
        r["ambiguous"] = bool(abs(r["score"] - thresh) <= AMB_BAND and not r["hard"])
    n_hp = sum(r["honeypot"] for r in recs)
    n_amb = sum(r["ambiguous"] for r in recs)
    print(f"\nhoneypot selection: target {hp_frac:.0%} (~{n_target}), "
          f"score threshold {thresh:.3f}, flagged {n_hp} "
          f"({100*n_hp/len(recs):.1f}%; incl. hard violators)")

    # ---- PASS 2: apply honeypot zeroing, write LAS + provenance ----
    prov, all_issues = [], []
    gatesum = n_pay = 0.0
    for r in recs:
        if r["honeypot"]:
            r["curves"]["PAY_FLAG"] = np.zeros_like(r["curves"]["PAY_FLAG"])
            r["net_pay"] = 0.0
        write_las(os.path.join(OUT, f"{r['wid']}.las"), r["wid"], r["depth"], r["curves"])
        issues = validate(r["curves"])
        if issues: all_issues.append((r["wid"], ",".join(issues)))
        gatesum += r["gate"]
        if r["net_pay"] > 0: n_pay += 1
        prov.append(dict(
            well_id=r["wid"], GR=r["prov"].get("GR", ""), Rt=r["prov"].get("RES_DEEP", ""),
            NPHI=r["prov"].get("NPHI", ""), rw_used=round(r["rw"], 4),
            honeypot=int(r["honeypot"]), ambiguous=int(r["ambiguous"]),
            honeypot_score=r["score"], honeypot_reason=r["reason"],
            net_pay_ft=round(r["net_pay"], 1), gate_pass_frac=round(r["gate"], 4),
            qc_flags=r["qc"], issues=";".join(issues)))

    with open(os.path.join(OUT, "provenance.csv"), "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(prov[0].keys())); wr.writeheader(); wr.writerows(prov)

    # ---- decisions worktable: deterministic = REFERENCE, agent = FINAL judge ----
    # The agent edits this then runs finalize_submission.py. Columns:
    #   honeypot  -> agent's FINAL honeypot 0/1 (default = honeypot_ref)
    #   pay_action-> accept | zero | recompute   (recompute uses the ov_* overrides)
    #   ov_*      -> per-well parameter overrides (blank = use reference default)
    # ov_* = per-well physical overrides the agent may set (default = key-aligned);
    # gr endpoints, matrix/fluid density, Archie m/n, Rw genuinely vary per well.
    # Full control surface: numeric param overrides + string METHOD overrides
    # (all consumed by finalize_submission -> petrophysics.compute_suite). Blank = default.
    ov_cols = ["ov_gr_clean", "ov_gr_shale", "ov_rho_ma", "ov_rho_fl", "ov_m", "ov_n",
               "ov_rw", "ov_rsh", "ov_vsh_cut", "ov_phie_cut", "ov_sw_cut", "ov_swirr_floor",
               "ov_vsh_method", "ov_phit_method", "ov_sw_method", "ov_perm_method"]
    dcols = ["well_id", "honeypot_ref", "honeypot", "honeypot_score", "ambiguous",
             "pay_action"] + ov_cols + ["net_pay_ref", "notes"]
    with open(os.path.join(OUT, "decisions.csv"), "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=dcols); wr.writeheader()
        for r in recs:
            row = {c: "" for c in dcols}
            row.update(well_id=r["wid"], honeypot_ref=int(r["honeypot"]),
                       honeypot=int(r["honeypot"]), honeypot_score=r["score"],
                       ambiguous=int(r["ambiguous"]), pay_action="accept",
                       net_pay_ref=round(r["net_pay"], 1), notes=r["reason"])
            wr.writerow(row)

    print(f"\n=== SUBMISSION BUILT ({rw_mode} Rw) ===")
    print(f"wells written:                 {len(recs)}")
    print(f"honeypots (PAY_FLAG=0):        {n_hp} ({100*n_hp/len(recs):.1f}%)")
    print(f"AMBIGUOUS (agent should review):{n_amb} -> provenance.csv ambiguous=1")
    print(f"real wells with net pay > 0:   {int(n_pay)}")
    print(f"avg Axis-1 gate pass-fraction: {gatesum/len(recs):.4f}")
    print(f"wells with validation issues:  {len(all_issues)}")
    for wid, iss in all_issues[:10]:
        print(f"   {wid[:12]}: {iss}")
    print(f"\noutput -> submission/  ({len(recs)} LAS + provenance.csv)")


if __name__ == "__main__":
    main()
