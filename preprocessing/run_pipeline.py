"""
Run the full preprocessing pipeline over all 800 raw LAS files using
las_preprocessor.parse_well, and write the processed artifacts:

  processed/wells/<id>.csv   normalized canonical curves (depth-indexed)
  processed/well_features.csv per-well feature/clustering matrix (+ key metadata)
  processed/curve_catalog.csv raw->canonical provenance per curve
  processed/well_metadata.csv depth frame + ~Params (Rw inputs) per well
  processed/manifest.json     coverage summary

Usage: python preprocessing/run_pipeline.py
"""
from __future__ import annotations
import csv, glob, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import las_preprocessor as lp  # noqa: E402

RAW = os.path.join(ROOT, "no_second_guessing_evaluation_data")
OUT = os.path.join(ROOT, "processed")
WELLS = os.path.join(OUT, "wells")
os.makedirs(WELLS, exist_ok=True)

STAT_FAMS = ["GR", "RHOB", "NPHI", "SONIC", "PEF", "CAL", "SP",
             "RES_DEEP", "RES_MED", "RES_SHAL"]


def stats(d):
    fin = d[np.isfinite(d)]
    if fin.size == 0:
        return None
    return dict(p10=np.percentile(fin, 10), p50=np.percentile(fin, 50),
                p90=np.percentile(fin, 90), std=np.std(fin), n=fin.size)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return ""


def pval(p, key):
    """~Params value (numeric if possible) or ''."""
    if key not in p:
        return ""
    v = p[key].get("value", "")
    return num(v) if num(v) != "" else v


def main():
    files = sorted(glob.glob(os.path.join(RAW, "*.las")))
    print(f"found {len(files)} LAS files")
    well_rows, cat_rows = [], []
    fam_present = {f: 0 for f in STAT_FAMS}
    n_ok = 0

    for i, path in enumerate(files):
        w = lp.parse_well(path)
        if "error" in w:
            print("  ERR", w["well_id"], w["error"]); continue
        wid = w["well_id"]; nrows = w["n_samples"]; curves = w["curves"]
        p = w["metadata"]["params"]

        # ---- per-well normalized curve CSV ----
        cols = [f for f in lp.PETRO if f in curves]
        arr = np.column_stack([curves[c] for c in cols])
        with open(os.path.join(WELLS, f"{wid}.csv"), "w", newline="") as fh:
            wr = csv.writer(fh); wr.writerow(cols)
            for row in arr:
                wr.writerow(["" if not np.isfinite(v) else f"{v:.5g}" for v in row])

        # ---- per-curve catalog (stays separate: per-curve, not per-well) ----
        for c in w["catalog"]:
            cat_rows.append(dict(well_id=wid, mnemonic=c["mnemonic"], unit=c["unit"],
                                 family=c["family"], valid=c["valid"], norm_note=c["norm"]))

        # ---- merged per-well row: identity + ~Params metadata + curve stats ----
        row = dict(well_id=wid, n_samples=nrows, n_raw_curves=len(w["catalog"]),
                   depth_start=round(w["depth_start"], 2), depth_stop=round(w["depth_stop"], 2),
                   depth_step=w["depth_step"], null_value=w["null_value"])
        # full ~Params block (mud + temperature + Rw inputs)
        row["mud"] = p.get("MUD", {}).get("value", "") if "MUD" in p else ""
        row["mw"] = pval(p, "MW"); row["mw_unit"] = p.get("MW", {}).get("unit", "") if "MW" in p else ""
        row["bht"] = pval(p, "BHT"); row["bht_unit"] = p.get("BHT", {}).get("unit", "") if "BHT" in p else ""
        row["bhs"] = pval(p, "BHS")
        row["rmf"] = pval(p, "RMF"); row["rmft"] = pval(p, "RMFT")
        row["rm"] = pval(p, "RM"); row["rmt"] = pval(p, "RMT")
        row["rmf_formation_temp"] = w["rmf_formation_temp"] if w["rmf_formation_temp"] else ""
        # per-family presence + robust stats
        for fam in STAT_FAMS:
            present = fam in curves
            row[f"has_{fam}"] = int(present)
            if present:
                fam_present[fam] += 1
                d = curves[fam]
                if fam.startswith("RES"):
                    d = np.log10(np.where(d > 0, d, np.nan))
                s = stats(d)
                if s:
                    for k in ("p10", "p50", "p90", "std"):
                        row[f"{fam}_{k}"] = round(float(s[k]), 4)
                    row[f"{fam}_null"] = round(1 - s["n"] / nrows, 4)
            else:
                for k in ("p10", "p50", "p90", "std", "null"):
                    row[f"{fam}_{k}"] = ""
        # cross-curve physics
        if "RHOB" in curves and "NPHI" in curves:
            phid = (2.65 - curves["RHOB"]) / 1.65
            m = np.isfinite(phid) & np.isfinite(curves["NPHI"])
            if m.sum() > 10:
                sep = curves["NPHI"][m] - phid[m]
                row["dn_sep_p50"] = round(float(np.median(sep)), 4)
                row["phid_p50"] = round(float(np.median(phid[m])), 4)
        row.setdefault("dn_sep_p50", ""); row.setdefault("phid_p50", "")
        row["qc_flags"] = ";".join(w["qc_flags"])   # keep last
        well_rows.append(row)

        n_ok += 1
        if (i + 1) % 100 == 0:
            print(f"  processed {i+1}/{len(files)}")

    # ---- write outputs (union of keys for ragged rows) ----
    def write(path, rows):
        keys = []
        for r in rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(path, "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=keys); wr.writeheader(); wr.writerows(rows)

    write(os.path.join(OUT, "well_features.csv"), well_rows)   # merged per-well table
    write(os.path.join(OUT, "curve_catalog.csv"), cat_rows)
    # remove the now-merged standalone metadata file if present
    old = os.path.join(OUT, "well_metadata.csv")
    if os.path.exists(old):
        os.remove(old)

    manifest = dict(n_files=len(files), n_processed=n_ok,
                    family_presence_pct={f: round(100 * fam_present[f] / max(n_ok, 1), 1)
                                         for f in STAT_FAMS})
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"\n=== DONE: {n_ok}/{len(files)} wells ===")
    print("family presence (% wells):")
    for f in STAT_FAMS:
        print(f"  {f:10s} {manifest['family_presence_pct'][f]:5.1f}%")
    nmud = sum(1 for r in well_rows if r.get("mud"))
    nrmf = sum(1 for r in well_rows if r["rmf_formation_temp"] != "")
    print(f"\nmetadata: MUD on {nmud}/{n_ok}, Rmf@Tf computed on {nrmf}/{n_ok}")
    print("outputs -> processed/{wells/, well_features.csv (merged), curve_catalog.csv, manifest.json}")


if __name__ == "__main__":
    main()
