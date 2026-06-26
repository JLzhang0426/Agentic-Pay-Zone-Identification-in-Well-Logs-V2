"""
Petrophysical compute ENGINE for the "No Second Guessing" challenge — pure
infrastructure, NOT the model. It executes whatever per-well interpretation the
ANALYSIS AGENT supplies; the petrophysical reasoning and the current-best values
live in the skills (skills/well-log-analysis, skills/honeypot-detection), applied
per well through `submission/decisions.csv` overrides.

compute_suite(parsed_well, overrides=...) -> dict of per-depth arrays:
  VSH, PHIT, PHIE, SW, PERM, PAY_FLAG  (+ intermediates, badhole, honeypot_score, gates)

The agent picks per-well PARAMETERS (gr endpoints, matrix, Rw, cutoffs, Rsh...) AND
per-well METHODS (`vsh_method`/`phit_method`/`sw_method`/`perm_method`) via
`overrides`; every transform lives in petro_formulas.py. The constants below are
LAST-RESORT FALLBACKS so the engine runs standalone — they are NOT the answer key
and NOT an interpretation; the agent is expected to override the interpretation
ones per well.
"""
from __future__ import annotations
import numpy as np
import petro_formulas as F

# ---- standard PHYSICAL constants (textbook; agent overrides for non-sandstone) ----
RHO_MA, RHO_FL = 2.65, 1.00           # quartz-sand matrix / fresh-water fluid g/cc
DT_MA, DT_FL = 55.5, 189.0            # Wyllie sandstone matrix / fluid slowness
A, M, N = 0.62, 2.15, 2.00            # Archie tortuosity / cementation / saturation
TIMUR_C, TIMUR_PHI, TIMUR_SW = 0.136, 4.4, 2.0
TIMUR_PORO_PERCENT = True             # standard Timur takes porosity/Swirr in PERCENT

# ---- INTERPRETATION fallbacks — the AGENT's decisions (see skills/well-log-analysis);
#      these are neutral last-resort values only, always overridable per well ----
GR_CLEAN, GR_SHALE = 20.0, 120.0      # GR endpoints: set per well from the histogram
RW_FIX = 0.05                         # Rw: set per well from Pickett / metadata
VSH_CUT, PHIE_CUT, SW_CUT = 0.40, 0.06, 0.45   # pay cutoffs: the agent's call per the skill


def assumptions() -> dict:
    """Snapshot of the engine's FALLBACK defaults (the methods/params used when the
    agent overrides nothing) — captured into each run's ledger so a score can be
    traced to its config. The agent's per-well deviations are recorded separately by
    run_ledger from decisions.csv; the model itself lives in the skills."""
    return {
        "vsh": {"gr_clean": GR_CLEAN, "gr_shale": GR_SHALE, "model": "linear"},
        "porosity": {"rho_ma": RHO_MA, "rho_fl": RHO_FL, "dt_ma": DT_MA,
                     "dt_fl": DT_FL, "phit": "mean(PHID,PHIN)+Wyllie gap-fill",
                     "phie": "PHIT*(1-VSH)"},
        "sw": {"archie_a": A, "archie_m": M, "archie_n": N, "rw_fixed": RW_FIX,
               "no_rt_fallback": "SW=1.0"},
        "perm": {"model": "Timur", "c": TIMUR_C, "phi_exp": TIMUR_PHI,
                 "sw_exp": TIMUR_SW, "swirr": "=SW", "units": "linear mD",
                 "poro_units": "percent" if TIMUR_PORO_PERCENT else "fraction"},
        "pay": {"vsh_cut": VSH_CUT, "phie_cut": PHIE_CUT, "sw_cut": SW_CUT},
        "badhole": "CAL > BHS + 2 in -> no pay",
        "honeypot": {"hard_threshold": HARD_HONEYPOT,
                     "score": "1.5*gas_imp + dn_cross + phid_oob + max(0,0.5-corr_GRNPHI)"},
        "coverage": "gap-fill computed curves; full depth; PAY=0 padding",
    }


def _interp_fill(depth: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Linear-interpolate NaNs within the logged interval; edge-hold."""
    m = np.isfinite(y)
    if m.sum() < 2:
        return y
    out = y.copy()
    out[~m] = np.interp(depth[~m], depth[m], y[m])
    return out


def _corr(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 20 or np.std(a[m]) < 1e-9 or np.std(b[m]) < 1e-9:
        return np.nan
    return float(np.corrcoef(a[m], b[m])[0, 1])


HARD_HONEYPOT = 0.30   # score above which violations are unambiguous

def honeypot_score(gr, rhob, nphi, phid) -> tuple[float, str]:
    """CONTINUOUS physics-violation score, defined for EVERY well (0 = clean),
    so the builder can rank all 800 wells and zero pay on the most honeypot-like
    ~25%. Higher = more physically impossible. Components are absolute per-well
    fractions (no cross-well norm needed) plus a GR-NPHI inversion penalty."""
    reasons = []
    score = 0.0
    if rhob is not None and nphi is not None:
        m = np.isfinite(rhob) & np.isfinite(nphi)
        if m.sum() > 20:
            # rock denser than quartz matrix yet high neutron porosity = impossible
            gas_imp = float(((rhob[m] > 2.68) & (nphi[m] > 0.30)).mean())
            score += 1.5 * gas_imp
            if gas_imp > 0.05: reasons.append(f"neutron-density impossible {gas_imp:.0%}")
    if phid is not None and nphi is not None:
        m = np.isfinite(phid) & np.isfinite(nphi)
        if m.sum() > 20:
            dn_cross = float((np.abs(nphi[m] - phid[m]) > 0.55).mean())
            score += 1.0 * dn_cross
            if dn_cross > 0.15: reasons.append(f"DN crossover {dn_cross:.0%}")
    if phid is not None:
        fin = phid[np.isfinite(phid)]
        if fin.size > 20:
            oob = float(((fin < -0.12) | (fin > 0.60)).mean())
            score += 1.0 * oob
            if oob > 0.15: reasons.append(f"density-porosity OOB {oob:.0%}")
    c = _corr(gr, nphi) if (gr is not None and nphi is not None) else np.nan
    if np.isfinite(c):
        pen = max(0.0, 0.50 - c)            # expected GR-NPHI ~0.9; penalize low/inverted
        score += pen
        if c < 0.0: reasons.append(f"GR-NPHI inverted r={c:.2f}")
    return round(score, 4), "; ".join(reasons)


# ---- Axis-1 physics gates (per-sample pass fraction) ----
def compute_gates(d: dict) -> tuple[dict, float]:
    def frac(mask, ref):
        v = np.isfinite(ref)
        return float(mask[v].mean()) if v.sum() else np.nan
    vsh, phit, phie, sw, perm = d["VSH"], d["PHIT"], d["PHIE"], d["SW"], d["PERM"]
    phid, gr, rhob, nphi, rt = d["PHID"], d.get("GR_raw"), d.get("RHOB_raw"), d.get("NPHI_raw"), d.get("RT_raw")
    g = {
        "vsh_0_1": frac((vsh >= 0) & (vsh <= 1), vsh),
        "phit_0_1": frac((phit >= 0) & (phit <= 1), phit),
        "phie_0_1": frac((phie >= 0) & (phie <= 1), phie),
        "phie_le_phit": frac(phie <= phit + 1e-6, phie),
        "sw_0_1": frac((sw >= 0) & (sw <= 1), sw),
        "perm_nonneg": frac(perm >= 0, perm),
        "perm_finite": frac(np.isfinite(perm), perm),
        "vsh_finite": frac(np.isfinite(vsh), vsh),
        "phie_finite": frac(np.isfinite(phie), phie),
        "sw_finite": frac(np.isfinite(sw), sw),
        "phid_bounds": frac((phid >= -0.15) & (phid <= 0.6), phid),
    }
    if gr is not None: g["gr_nonneg"] = frac(gr >= 0, gr)
    if gr is not None: g["gr_le300"] = frac(gr <= 300, gr)
    if rhob is not None: g["rhob_phys"] = frac((rhob >= 1.0) & (rhob <= 3.05), rhob)
    if nphi is not None: g["nphi_phys"] = frac((nphi >= -0.05) & (nphi <= 1.0), nphi)
    if rt is not None: g["rt_pos"] = frac(rt > 0, rt)
    if rhob is not None and nphi is not None:
        m = np.isfinite(rhob) & np.isfinite(nphi)
        g["dn_consistent"] = frac(np.abs(nphi - phid) <= 0.55, np.where(m, phid, np.nan))
    vals = [v for v in g.values() if np.isfinite(v)]
    return g, (float(np.mean(vals)) if vals else 0.0)


def compute_suite(w: dict, rw_mode: str = "fixed", fill: bool = True,
                  overrides: dict | None = None) -> dict:
    """w = las_preprocessor.parse_well output.

    `overrides` lets the AGENT recompute a single well with different parameters
    (the deterministic constants are only a reference): keys gr_clean, gr_shale,
    vsh_cut, phie_cut, sw_cut, a, m, n, rw.
    """
    ov = overrides or {}
    gr_clean = float(ov.get("gr_clean", GR_CLEAN)); gr_shale = float(ov.get("gr_shale", GR_SHALE))
    vsh_cut = float(ov.get("vsh_cut", VSH_CUT)); phie_cut = float(ov.get("phie_cut", PHIE_CUT))
    sw_cut = float(ov.get("sw_cut", SW_CUT))
    a = float(ov.get("a", A)); m = float(ov.get("m", M)); n_arch = float(ov.get("n", N))
    rho_ma = float(ov.get("rho_ma", RHO_MA)); rho_fl = float(ov.get("rho_fl", RHO_FL))
    swirr_floor = float(ov.get("swirr_floor", 0.0))   # A4 PERM lever: bulk-volume-water / irreducible-Sw floor

    cur = w["curves"]; depth = cur["DEPTH"]; n = depth.size
    gr = cur.get("GR"); rhob = cur.get("RHOB"); nphi = cur.get("NPHI")
    rt = cur.get("RES_DEEP"); cal = cur.get("CAL"); son = cur.get("SONIC")
    nan = np.full(n, np.nan)

    # --- Rw: explicit override > per-well metadata (toggle) > fixed key value ---
    if "rw" in ov and ov["rw"] not in (None, ""):
        rw = float(ov["rw"])
    elif rw_mode == "metadata" and w.get("rmf_formation_temp"):
        rw = float(w["rmf_formation_temp"])
    else:
        rw = RW_FIX

    # --- per-well METHOD selection (defaults reproduce the reference recipe) ---
    vsh_method = str(ov.get("vsh_method", "linear")).strip().lower() or "linear"
    phit_method = str(ov.get("phit_method", "dn_avg")).strip().lower() or "dn_avg"
    sw_method = str(ov.get("sw_method", "archie")).strip().lower() or "archie"
    perm_method = str(ov.get("perm_method", "timur")).strip().lower() or "timur"

    # --- VSH (GR-index family; method-selectable) ---
    if gr is not None:
        vsh = F.VSH_METHODS.get(vsh_method, F.vsh_linear)(F.igr(gr, gr_clean, gr_shale))
    else:
        vsh = nan.copy()

    # --- porosity ---
    phid = F.phid(rhob, rho_ma, rho_fl) if rhob is not None else nan.copy()
    phin = nphi if nphi is not None else nan.copy()
    phit = F.PHIT_METHODS.get(phit_method, F.phit_dn_avg)(phid, phin)
    if son is not None:   # Wyllie sonic fills gaps where neither density nor neutron is present
        phis = F.phis_wyllie(son, DT_MA, DT_FL)
        gap = ~np.isfinite(phit) & np.isfinite(phis)
        phit[gap] = phis[gap]
    phit = np.clip(phit, 0, 1)
    phie = F.phie_simple(phit, vsh)
    phie[~np.isfinite(phit)] = np.nan

    # --- SW (method-selectable; shaly-sand models lower Sw vs Archie; no-Rt -> water-wet) ---
    if rt is not None:
        if sw_method in ("simandoux", "indonesia"):
            shp = F.estimate_shale_props(vsh, rhob=rhob, nphi=nphi, rt=rt, rho_ma=rho_ma, rho_fl=rho_fl)
            rsh = shp["rsh"]
            if ov.get("rsh") not in (None, ""):
                try: rsh = float(ov["rsh"])
                except (TypeError, ValueError): pass
            if not np.isfinite(rsh): rsh = 1e9        # no shale info -> shaly term vanishes (~Archie)
            sw = F.SW_METHODS[sw_method](
                phie, rt, vsh=np.where(np.isfinite(vsh), vsh, 0.0), rsh=rsh,
                rw=rw, a=a, m=m, n=n_arch)
        else:
            sw = F.sw_archie(phie, rt, rw=rw, a=a, m=m, n=n_arch)
    else:
        sw = np.ones(n)            # water-wet fallback, invents no pay

    # --- PERM (method-selectable; SUBMIT linear mD) ---
    # swirr defaults to in-situ SW; ov swirr_floor raises it to an irreducible/BVW floor
    swirr = np.clip(np.maximum(sw, swirr_floor), 0.01, 1.0)
    if perm_method == "timur":
        perm = F.perm_timur(phie, swirr, c=TIMUR_C, phi_exp=TIMUR_PHI, sw_exp=TIMUR_SW,
                            percent=TIMUR_PORO_PERCENT)
    else:
        perm = F.PERM_METHODS.get(perm_method, F.perm_timur)(phie, swirr)

    # --- gap-fill computed curves across the logged interval (Axis-4 coverage) ---
    if fill:
        for arr in (vsh, phit, phie, sw, perm):
            arr[:] = _interp_fill(depth, arr)
        vsh = np.clip(vsh, 0, 1); phit = np.clip(phit, 0, 1)
        phie = np.clip(np.minimum(phie, phit), 0, 1); sw = np.clip(sw, 0, 1)
        perm = np.clip(perm, 0, None)

    # --- Stage 2: bad-hole mask ---
    bs = None
    p = w["metadata"]["params"]
    if "BHS" in p:
        try: bs = float(p["BHS"]["value"])
        except (TypeError, ValueError): bs = None
    badhole = np.zeros(n, bool)
    if cal is not None and bs is not None:
        badhole = np.isfinite(cal) & (cal > bs + 2.0)

    # --- Stage 2: honeypot SCORE (continuous; global selection done by builder) ---
    hp_score, hp_reason = honeypot_score(gr, rhob, nphi, phid)
    hp_hard = hp_score >= HARD_HONEYPOT

    # --- PAY_FLAG (cutoff pay; honeypot zeroing applied globally in builder) ---
    pay = ((vsh <= vsh_cut) & (phie >= phie_cut) & (sw <= sw_cut) & ~badhole)
    pay = pay.astype(float)
    pay[~(np.isfinite(vsh) & np.isfinite(phie) & np.isfinite(sw))] = 0.0

    out = dict(DEPTH=depth, VSH=vsh, PHIT=phit, PHIE=phie, SW=sw, PERM=perm,
               PAY_FLAG=pay, PHID=phid, badhole=badhole,
               honeypot_score=hp_score, honeypot_reason=hp_reason, honeypot_hard=hp_hard,
               rw_used=rw, GR_raw=gr, RHOB_raw=rhob, NPHI_raw=nphi, RT_raw=rt)
    gates, gate_pass = compute_gates(out)
    out["gates"] = gates; out["gate_pass_frac"] = gate_pass
    step = float(np.median(np.abs(np.diff(depth)))) if n > 1 else 0.5
    out["net_pay_ft"] = float(np.nansum(pay) * step)
    return out
