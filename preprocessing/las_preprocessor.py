"""
LAS preprocessor for the "No Second Guessing" challenge.

Builds on the skill parser
(oil-and-gas-claude-skills/skills/oil_and_gas_data_manager/parsers/las_parser.py)
— reuses its lasio backbone, NULL handling and ~Well field map — and extends it
with what this dataset needs:

  1. Full canonical family resolver (219 mnemonics) using name + unit-class +
     value magnitude, because unit strings here are deliberately unreliable.
  2. PHYSICS-aware member selection for the curves that drive every output:
       - resistivity Rt chosen by depth-of-investigation (deepest), not by which
         mnemonic is most common — short array spacings (A16H..A34H), SFL/SFLU/LLS
         are NOT deep and must not be used as Rt;
       - GR prefers TOTAL gamma over uranium-free computed (CGR/HCGR), even if the
         computed curve is more complete;
       - NPHI prefers true neutron over PHIS (sonic porosity);
       - SONIC prefers compressional over shear (value-guarded).
     For these four, physics preference dominates; completeness only breaks ties.
  3. ~Params extraction (BHT, RMF, RMFT, RM, RMT, MW, BHS, MUD) -> per-well Rw.
  4. Value-driven unit normalization (us/m sonic, mm caliper, % NPHI).

Dependency-light: lasio + numpy (+ stdlib). Import-safe.
"""
from __future__ import annotations
import glob, os, sys
import numpy as np

try:
    import lasio
    HAS_LASIO = True
except ImportError:
    HAS_LASIO = False

# --------------------------------------------------------------------------
# Unit class from a (often wrong) unit string
# --------------------------------------------------------------------------
def unit_class(unit: str | None) -> str:
    u = (unit or "").strip().upper()
    if u == "":
        return "blank"
    if "OHM" in u or u == "HMOH":
        return "res"
    if "API" in u or u == "CPS":
        return "gamma"
    if any(k in u for k in ("G/CC", "G/C3", "GM/CC", "G/CM3", "GM/C3")):
        return "density"
    if u in ("V/V", "M3/M3", "DEC", "FRAC", "PU", "%") or "/V" in u:
        return "neutron"
    if "US/" in u or "USEC" in u or "MICROSEC" in u or u in ("USFT", "US/F"):
        return "sonic"
    if u in ("IN", "INCH", "INCHES", "INS", "CM", "MM"):
        return "cal"
    if u in ("MV", "V", "MVOL", "MILLIVOLT"):
        return "sp"
    if "B/E" in u or "BARN" in u or u == "B/EL":
        return "pe"
    if u == "DEG":
        return "angle"
    return "other"

# name hints (uppercase mnemonic -> family); unit_class overrides wrong names
_NAME: dict[str, str] = {}
def _add(fam, names):
    for n in names: _NAME[n.upper()] = fam
_add("GR", "GR GRD GRR GRS GRN GR1 GR2 SGR CGR HCGR ECGR HSGR GRGC GR_EDTC HGR HGRC HGRCC NGRT GKUT GRAM GRTO GR_SL EHGR GCGR GRC".split())
_add("RHOB", "RHOB RHOZ ZDEN DEN DENS DENB DENC FDC RHOB_CDL ZDNC RHOBC ZDENS RHOM RHBH ROBB HDEN EDRA RHOZE DEN_COR HDRA HDRHO".split())
_add("NPHI", "NPHI TNPH NPOR CNCF APLC NEU NEUT CNL BPHI PHIN HNPO NPHI_CDL APLS NPRL SNPH TNPS ENPH NPRS HTNP TCNL TNPB NPOR_LS CNC PHIS".split())
_add("SONIC", "DT DTC DTCO AC SONIC BHC DTLN SON DTL EDTC HDTC DT1R DT_BHC SLOWNESS DTBHC DT1 DT24 DTCO4 DT4P SONICDT DTSH DTLN_MRK DT4S DTSM DTS".split())
_add("PEF", "PEF PE PEFZ PEFA HPEF HDPE PEFN PEDN PE_CDL PPEN PEZ PEF8 PE8 ENPE PEFL PEFLA PEZL HDPEF".split())
_add("CAL", "CAL CALI HCAL CALS DCAL LCAL CAL_CDL CALDC CAL1 CAL2 ECAL CALR CALD CALX C1 C2 CLDC TAB HCALS".split())
_add("SP", "SP SSP SPONT SP_MV SPC SPR PSP SPM SPHI SPNT SPONPOT ESP SPOT".split())
_add("AUX", "WOB TORQ SWOB ROP RPM TENS TT1 TT2 HAZI DEVI TEMP PRES BSAL ECD MUDW X1 X2 UNKNOWN DRHO".split())
# resistivity name hints retained only to recognise blank-unit resistivity curves
_RES_NAMES = set("RT ILD RILD LLD RLLD RD RESD AT90 AHT90 AHF90 AO90 RT_HRLT IDPH RLA5 AO90 M2R9 AIT_H90 RAILD HLLD A16H A22H A28H A34H P16H RB RLLA ILM SFL SFLU LLS RS HDRS HMRS RLA1 AO10 AHO10 SGRD HMIN RSFL RXO RXOZ MSFL MLL MCFL RXO8 RXO_HRLT RMLL SN RXORT".split())
_DEPTH = {"DEPT", "DEPTH", "MD", "TDEP", "DEP", "DEPH", "MDEPTH", "TVD", "TVDSS"}

# physics sub-classes for the critical curves
GR_COMPUTED = {"CGR", "HCGR"}            # uranium-free (Th+K) -> under-reads shale
NPHI_SONIC = {"PHIS"}                    # sonic porosity, not neutron
SONIC_SHEAR = {"DT4S", "DTSM", "DTS"}    # shear slowness, not compressional

# resistivity depth-of-investigation proxy (inches). Higher = deeper ~ Rt.
RES_DOI = {
    # micro / Rxo (shallowest)
    "RXO": 2, "RXOZ": 2, "MSFL": 2, "MLL": 2, "MCFL": 2, "RXO8": 3,
    "RXO_HRLT": 2, "RMLL": 2, "SN": 4, "RXORT": 2,
    # shallow focused / laterolog-shallow
    "SFL": 10, "SFLU": 10, "SGRD": 10, "RSFL": 10, "RS": 12, "LLS": 20,
    "RLA1": 12, "AHO10": 10, "AO10": 10,
    # array induction by explicit spacing
    "A16H": 16, "P16H": 16, "A22H": 22, "A28H": 28, "A34H": 34,
    # medium induction / laterolog
    "ILM": 30, "RILM": 30, "HMRS": 30, "HDRS": 40, "HMIN": 30,
    # deep (~Rt)
    "RT": 90, "ILD": 90, "LLD": 90, "RILD": 90, "RLLD": 90, "RD": 90,
    "RESD": 90, "RT_HRLT": 90, "IDPH": 85, "RLA5": 90, "M2R9": 90,
    "AIT_H90": 90, "RAILD": 90, "HLLD": 90, "RLLA": 90, "RB": 80,
    "AT90": 90, "AHT90": 90, "AHF90": 90, "AO90": 90,
}
RES_DOI_DEFAULT = 30   # unknown resistivity assumed medium

PETRO = ["DEPTH", "GR", "RHOB", "NPHI", "SONIC", "PEF", "CAL", "SP",
         "RES_DEEP", "RES_MED", "RES_SHAL"]
NORMALIZE_FAMS = set(PETRO) | {"RES"}
NAME_PRIORITY = {
    "GR": ["GR", "ECGR", "SGR", "HSGR"],
    "RHOB": ["RHOB", "RHOZ", "ZDEN", "DEN", "HDRA"],
    "NPHI": ["NPHI", "TNPH", "NPOR", "CNCF", "APLC"],
    "SONIC": ["DTCO", "DTC", "DT", "AC", "BHC"],
    "PEF": ["PEF", "PE", "PEFZ", "HPEF"],
    "CAL": ["CALI", "CAL", "HCAL", "DCAL"],
    "SP": ["SP", "SSP", "SPONT"],
}


def resolve_family(mnem: str, unit: str | None, median: float | None) -> str:
    m = (mnem or "").strip().upper()
    uc = unit_class(unit)
    name = _NAME.get(m)
    if m in _DEPTH:
        return "DEPTH"
    if uc == "angle" or name == "AUX":
        return "AUX"
    if uc == "res" or m in _RES_NAMES:
        return "RES"                       # sub-bin (deep/med/shal) decided by DOI
    if uc == "gamma":
        return "GR"
    if uc == "density":
        if m == "DRHO" or (median is not None and abs(median) < 0.6):
            return "DRHO"
        if median is not None and not (0.5 <= median <= 4.0):
            return "AUX"
        return "RHOB"
    if uc == "sonic":
        return "SONIC"
    if uc == "pe":
        return "PEF"
    if uc == "sp":
        return "SP"
    if uc == "cal":
        return "BS" if m in ("BS", "BIT") else "CAL"
    if uc == "neutron":
        return "NPHI" if (name == "NPHI" or (median is not None and -0.1 <= median <= 1.2)) else "AUX"
    if name:
        if name == "RHOB" and median is not None and not (1.0 <= median <= 3.6):
            return "AUX"
        return name
    return "AUX"


def normalize_values(fam: str, data: np.ndarray, unit: str | None):
    d = np.asarray(data, float)
    fin = d[np.isfinite(d)]
    if fin.size == 0:
        return d, "all-null"
    med = float(np.median(fin)); note = ""
    if fam == "NPHI" and med > 1.5:
        d = d / 100.0; note = "pct->frac"
    elif fam == "SONIC" and med > 180:
        d = d / 3.28084; note = "us/m->us/ft"
    elif fam == "CAL":
        if med > 60: d = d / 25.4; note = "mm->in"
        elif 14 < med <= 60: d = d / 2.54; note = "cm->in"
    elif fam == "SP" and (unit or "").strip().upper() == "V" and abs(med) < 3:
        d = d * 1000.0; note = "V->mV"
    elif fam == "RES":
        d = np.where(d <= 0, np.nan, d); note = "nonpos->nan"
    return d, note


def pick_member(fam: str, cands: list[dict]) -> dict:
    """Physics-preference picker: demote physically-wrong members, then prefer
    completeness, then name priority. (Inverts the old completeness-first bug.)"""
    prio = NAME_PRIORITY.get(fam, [])

    def rank(c):
        m = c["mnem"]; demote = 0
        if fam == "GR" and m in GR_COMPUTED:
            demote = 1                         # prefer total GR over uranium-free
        if fam == "NPHI" and m in NPHI_SONIC:
            demote = 1                         # prefer true neutron over sonic poro
        if fam == "SONIC":
            if m in SONIC_SHEAR:
                demote = 1                     # prefer compressional over shear
            if c["median"] is not None and c["median"] > 120:
                demote = max(demote, 1)        # value-guard: shear Δt range
        p = prio.index(m) if m in prio else len(prio) + 1
        return (demote, -c["valid"], p)
    return sorted(cands, key=rank)[0]


# --------------------------------------------------------------------------
# Metadata extraction  (~Well depth frame + ~Params mud/temperature suite)
# --------------------------------------------------------------------------
_PARAM_KEYS = ["BHT", "RMF", "RMFT", "RM", "RMT", "MW", "BHS", "MUD"]

def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def extract_metadata(las) -> dict:
    md = {}
    for k in ("STRT", "STOP", "STEP", "NULL", "DATE"):
        try:
            md[k.lower()] = las.well[k].value
        except Exception:
            md[k.lower()] = None
    params = {}
    for k in _PARAM_KEYS:
        try:
            it = las.params[k]
            params[k] = dict(value=it.value, unit=(it.unit or ""))
        except Exception:
            pass
    for k in ("BHT_UNIT", "MW_UNIT"):
        try:
            params[k] = las.params[k].value
        except Exception:
            pass
    md["params"] = params
    return md


def formation_temp_corrected_rmf(params: dict, formation_temp_f: float | None = None):
    """Rmf corrected to formation temperature via Arps (degF). Returns (rmf_ft, T)."""
    rmf = _num(params.get("RMF", {}).get("value")) if "RMF" in params else None
    rmft = _num(params.get("RMFT", {}).get("value")) if "RMFT" in params else None
    bht = _num(params.get("BHT", {}).get("value")) if "BHT" in params else None
    if rmf is None or rmft is None:
        return None, None
    T = formation_temp_f if formation_temp_f is not None else bht
    if T is None:
        return rmf, rmft
    return rmf * (rmft + 6.77) / (T + 6.77), T


# --------------------------------------------------------------------------
# Main per-well parse
# --------------------------------------------------------------------------
def parse_well(path: str) -> dict:
    well_id = os.path.splitext(os.path.basename(path))[0]
    if not HAS_LASIO:
        return {"well_id": well_id, "error": "lasio unavailable"}
    try:
        las = lasio.read(path)
    except Exception as exc:  # noqa: BLE001
        return {"well_id": well_id, "error": f"parse_error: {exc}"}
    try:
        depth = np.asarray(las.index, float)
    except Exception:
        return {"well_id": well_id, "error": "no depth index"}

    nrows = depth.size
    step = float(np.median(np.abs(np.diff(depth)))) if nrows > 1 else float("nan")

    by_fam: dict[str, list] = {}
    catalog = []
    for c in las.curves:
        raw = np.asarray(c.data, float)
        fin = raw[np.isfinite(raw)]
        med = float(np.median(fin)) if fin.size else None
        fam = resolve_family(c.mnemonic, c.unit, med)
        ndata, note = normalize_values(fam, raw, c.unit) if fam in NORMALIZE_FAMS else (raw, "")
        fin2 = ndata[np.isfinite(ndata)]
        med2 = float(np.median(fin2)) if fin2.size else None
        valid = int(np.isfinite(ndata).sum())
        catalog.append(dict(mnemonic=c.mnemonic, unit=(c.unit or ""), family=fam,
                            valid=valid, norm=note))
        if fam in NORMALIZE_FAMS and valid > 0:
            by_fam.setdefault(fam, []).append(
                dict(mnem=c.mnemonic.upper(), valid=valid, data=ndata, median=med2))

    curves = {"DEPTH": depth}
    provenance = {"DEPTH": "index"}
    qc: list[str] = []

    # --- resistivity: assign DEEP/MED/SHAL by depth-of-investigation ---
    if "RES" in by_fam:
        res = by_fam["RES"]
        for r in res:
            r["doi"] = RES_DOI.get(r["mnem"], RES_DOI_DEFAULT)
        deep = max(res, key=lambda r: (r["doi"], r["valid"]))
        shal = min(res, key=lambda r: (r["doi"], -r["valid"]))
        curves["RES_DEEP"] = deep["data"]
        provenance["RES_DEEP"] = f"{deep['mnem']}(DOI~{deep['doi']})"
        if shal is not deep:
            curves["RES_SHAL"] = shal["data"]
            provenance["RES_SHAL"] = f"{shal['mnem']}(DOI~{shal['doi']})"
        mids = [r for r in res if r is not deep and r is not shal
                and shal["doi"] < r["doi"] < deep["doi"]]
        if mids:
            mid = max(mids, key=lambda r: (r["doi"], r["valid"]))
            curves["RES_MED"] = mid["data"]
            provenance["RES_MED"] = f"{mid['mnem']}(DOI~{mid['doi']})"
        if deep["doi"] < 60:
            qc.append("shallow_rt_fallback")

    # --- other families: physics-preference picker ---
    for fam in ["GR", "RHOB", "NPHI", "SONIC", "PEF", "CAL", "SP"]:
        if fam not in by_fam:
            continue
        best = pick_member(fam, by_fam[fam])
        curves[fam] = best["data"]
        provenance[fam] = best["mnem"]
        if fam == "GR" and best["mnem"] in GR_COMPUTED:
            qc.append("gr_uranium_free_only")
        if fam == "NPHI" and best["mnem"] in NPHI_SONIC:
            qc.append("porosity_from_sonic")
        if fam == "SONIC" and (best["mnem"] in SONIC_SHEAR or
                               (best["median"] is not None and best["median"] > 120)):
            qc.append("sonic_shear_suspect")

    md = extract_metadata(las)
    rmf_ft, T = formation_temp_corrected_rmf(md["params"])
    if "RES_DEEP" not in curves:
        qc.append("no_resistivity")
    if "NPHI" not in curves or "RHOB" not in curves:
        qc.append("incomplete_porosity")
    if rmf_ft is None:
        qc.append("no_rmf_params")

    return dict(
        well_id=well_id, n_samples=nrows,
        depth_start=float(np.nanmin(depth)), depth_stop=float(np.nanmax(depth)),
        depth_step=round(step, 4) if np.isfinite(step) else None,
        null_value=md.get("null"),
        curves=curves, provenance=provenance, catalog=catalog,
        metadata=md, rmf_formation_temp=(round(rmf_ft, 4) if rmf_ft else None),
        formation_temp_f=T, qc_flags=qc,
    )


def parse_all(las_dir: str):
    for p in sorted(glob.glob(os.path.join(las_dir, "*.las"))):
        yield parse_well(p)


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "no_second_guessing_evaluation_data"
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    n = 0
    for w in parse_all(d):
        if "error" in w:
            print("ERR", w["well_id"], w["error"]); continue
        pr = w["provenance"]
        print(f"{w['well_id'][:12]} | GR={pr.get('GR','-')} NPHI={pr.get('NPHI','-')} "
              f"Rt={pr.get('RES_DEEP','-')} Rxo={pr.get('RES_SHAL','-')} | QC={w['qc_flags']}")
        n += 1
        if limit and n >= limit:
            break
    print(f"\nparsed {n} wells")
