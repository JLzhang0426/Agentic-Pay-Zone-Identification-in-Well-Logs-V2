"""
Petrophysics formula TOOLBOX — the menu of methods the per-well agent flexibly picks
from (see skills/well-log-analysis/SKILL.md and docs/output_methods_study.md).

Every function is a pure, numpy-only transform on per-depth arrays. Each curve family
exposes several alternative methods plus a `*_METHODS` dispatch dict so the engine
(petrophysics.compute_suite) can select per well via an override like
`vsh_method="larionov_tertiary"` or `sw_method="indonesia"`.

Conventions: porosity & saturation as FRACTIONS [0,1] everywhere EXCEPT Timur PERM,
which uses PERCENT internally (handled inside perm_timur). All outputs clipped to
physical bounds. NaNs propagate (callers gap-fill).

Direction-of-effect notes in the docstrings tell you which way a method pushes a
scored curve (PHIE/SW/PERM are Axis-4 scored) — use them to choose an A/B.
"""
from __future__ import annotations
import numpy as np

# ============================ shale volume (VSH) ============================
# IGR = gamma-ray index; the transforms map IGR -> Vsh. Linear is the most
# PESSIMISTIC (highest Vsh); the non-linear forms are all more optimistic (lower
# Vsh), Larionov-Tertiary being the lowest. Higher Vsh -> lower PHIE (Axis-4).

def igr(gr, gr_clean, gr_shale):
    """Gamma-ray index, clipped [0,1]. `gr_clean`/`gr_shale` from the GR histogram
    (clean ~ low mode, shale ~ high mode)."""
    return np.clip((gr - gr_clean) / (gr_shale - gr_clean), 0.0, 1.0)


def vsh_linear(i):
    """Vsh = IGR. Most pessimistic (highest Vsh). Default / conservative."""
    return np.clip(i, 0, 1)


def vsh_larionov_tertiary(i):
    """Larionov (1969) young/Tertiary rocks: 0.083*(2^(3.7*IGR)-1). MOST OPTIMISTIC
    (lowest Vsh ~ half of linear). Use for young clastics where linear over-calls
    shale; RAISES PHIE."""
    return np.clip(0.083 * (2.0 ** (3.7 * i) - 1.0), 0, 1)


def vsh_larionov_older(i):
    """Larionov older/consolidated rocks: 0.33*(2^(2*IGR)-1). Between linear and
    Tertiary."""
    return np.clip(0.33 * (2.0 ** (2.0 * i) - 1.0), 0, 1)


def vsh_clavier(i):
    """Clavier: 1.7 - sqrt(3.38-(IGR+0.7)^2). Optimistic, close to Larionov."""
    return np.clip(1.7 - np.sqrt(np.clip(3.38 - (i + 0.7) ** 2, 0, None)), 0, 1)


def vsh_stieber(i):
    """Stieber: IGR/(3-2*IGR). Optimistic."""
    return np.clip(i / (3.0 - 2.0 * i), 0, 1)


def vsh_neutron_density(nphi, phid, nphi_sh, phid_sh):
    """Neutron-density Vsh = (NPHI-PHID)/(NPHIsh-PHIDsh). Independent of GR; good
    when GR is unreliable (CGR-only, feldspathic/hot sands). Needs shale points."""
    denom = (nphi_sh - phid_sh)
    if abs(denom) < 1e-6:
        return np.full_like(nphi, np.nan)
    return np.clip((nphi - phid) / denom, 0, 1)


VSH_METHODS = {
    "linear": vsh_linear, "larionov_tertiary": vsh_larionov_tertiary,
    "larionov_older": vsh_larionov_older, "clavier": vsh_clavier,
    "stieber": vsh_stieber,
}


# ============================ porosity (PHIT) ============================

def phid(rhob, rho_ma=2.65, rho_fl=1.0):
    """Density porosity (ρma−ρb)/(ρma−ρfl). Matrix: sand 2.65 / lime 2.71 / dol 2.87."""
    return (rho_ma - rhob) / (rho_ma - rho_fl)


def phis_wyllie(dt, dt_ma=55.5, dt_fl=189.0):
    """Wyllie time-average sonic porosity (Δt−Δtma)/(Δtfl−Δtma)."""
    return np.clip((dt - dt_ma) / (dt_fl - dt_ma), 0, 1)


def phis_rhg(dt, dt_ma=55.5):
    """Raymer-Hunt-Gardner sonic porosity 0.625*(1−Δtma/Δt). Better in unconsolidated
    / high-porosity sands than Wyllie."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.clip(0.625 * (1.0 - dt_ma / dt), 0, 1)


def phit_dn_avg(pd, pn):
    """Density-neutron arithmetic mean — default."""
    with np.errstate(invalid="ignore"):
        return np.nanmean(np.vstack([pd, pn]), axis=0)


def phit_dn_rms(pd, pn):
    """Density-neutron RMS sqrt((PHID²+PHIN²)/2). GAS-leaning (reads higher than the
    mean where density>neutron); use in known gas."""
    with np.errstate(invalid="ignore"):
        return np.sqrt((pd ** 2 + pn ** 2) / 2.0)


def phit_dn_gas(pd, pn):
    """Gas-corrected DN: density-weighted (toward PHID) where NPHI<PHID (gas
    crossover), else the mean. Reduces the gas-suppressed neutron's pull."""
    out = phit_dn_avg(pd, pn)
    gas = np.isfinite(pn) & np.isfinite(pd) & (pn < pd)
    out[gas] = (2.0 * pd[gas] + pn[gas]) / 3.0
    return out


PHIT_METHODS = {"dn_avg": phit_dn_avg, "dn_rms": phit_dn_rms, "dn_gas": phit_dn_gas}


# ============================ effective porosity (PHIE) ============================
# Axis-4 scored (τ=0.03).

def phie_simple(phit, vsh):
    """PHIT*(1−Vsh) — default."""
    return np.clip(phit * (1.0 - np.where(np.isfinite(vsh), vsh, 0.0)), 0, 1)


def phie_shale_sub(phit, vsh, phit_sh):
    """PHIT − Vsh*PHITsh — subtracts the shale's own (held) porosity. Needs the
    shale's total porosity PHITsh from a shale bed."""
    return np.clip(phit - vsh * phit_sh, 0, 1)


# ============================ water saturation (SW) ============================
# Axis-4 scored (τ=0.10). Archie is for clean sand; in shaly rock Archie
# OVER-estimates Sw, so Simandoux/Indonesia lower it (Indonesia lowest; can overshoot
# >100% in fresh / low-Rw). All ≈ Archie when Vsh→0.

def sw_archie(phie, rt, rw=0.05, a=0.62, m=2.15, n=2.0):
    """Archie ((a·Rw)/(PHIE^m·Rt))^(1/n). Clean-sand default."""
    with np.errstate(invalid="ignore", divide="ignore"):
        sw = (a * rw / (np.clip(phie, 1e-4, None) ** m * np.clip(rt, 1e-6, None))) ** (1.0 / n)
    return np.clip(sw, 0, 1)


def sw_simandoux(phie, rt, vsh, rsh, rw=0.05, a=0.62, m=2.15, n=2.0):
    """Simandoux (1963) shaly-sand, explicit n=2 solution:
       1/Rt = (PHIE^m/(a·Rw))·Sw² + (Vsh/Rsh)·Sw.
    Lowers Sw vs Archie in shale. (n is forced to 2 in this closed form.)"""
    C = np.clip(phie, 1e-4, None) ** m / (a * rw)
    D = np.where(rsh > 0, vsh / rsh, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        sw = (-D + np.sqrt(D ** 2 + 4.0 * C / np.clip(rt, 1e-6, None))) / (2.0 * C)
    return np.clip(sw, 0, 1)


def sw_indonesia(phie, rt, vsh, rsh, rw=0.05, a=0.62, m=2.15, n=2.0):
    """Indonesia / Poupon-Leveaux (1971) shaly-sand:
       1/√Rt = [Vsh^(1−Vsh/2)/√Rsh + √(PHIE^m/(a·Rw))]·Sw^(n/2).
    Yields the LOWEST Sw of the three; can overshoot in fresh water / very low Rw."""
    vterm = np.where(rsh > 0, vsh ** (1.0 - vsh / 2.0) / np.sqrt(rsh), 0.0)
    pterm = np.sqrt(np.clip(phie, 1e-4, None) ** m / (a * rw))
    with np.errstate(invalid="ignore", divide="ignore"):
        sw = (1.0 / np.sqrt(np.clip(rt, 1e-6, None)) / (vterm + pterm)) ** (2.0 / n)
    return np.clip(sw, 0, 1)


SW_METHODS = {"archie": sw_archie, "simandoux": sw_simandoux, "indonesia": sw_indonesia}


# ============================ Rw estimators ============================

def rw_pickett(phie, rt, a=0.62, m=2.15, wet_quartile=0.25, phi_min=0.08):
    """Estimate Rw from the SW=1 (water) envelope of a Pickett crossplot. The water
    line is RT = a·Rw/PHIE^m, so Rw = median(RT·PHIE^m/a) over the wettest (lowest-RT)
    porous samples. Returns a scalar (np.nan if too few points)."""
    msk = np.isfinite(phie) & np.isfinite(rt) & (phie > phi_min) & (rt > 0)
    if msk.sum() < 15:
        return np.nan
    p, r = phie[msk], rt[msk]
    wet = r <= np.percentile(r, 100 * wet_quartile)
    if wet.sum() < 8:
        return np.nan
    return float(np.median(r[wet] * p[wet] ** m / a))
# (Automated m-from-Pickett-slope is intentionally omitted — robust cementation-
#  exponent fitting needs interactive water-line QC. Build a Pickett crossplot from
#  the curves and read m by eye; use rw_pickett above for the automated Rw prior.)


# ============================ permeability (PERM) ============================
# Axis-4 scored as log10(k), τ=0.5 decade. SUBMIT LINEAR mD. Timur uses PERCENT
# porosity (fraction is ~10^4.8 too low — a settled bug fix).

def perm_timur(phie, swirr, c=0.136, phi_exp=4.4, sw_exp=2.0, percent=True):
    """Timur (1968) k = 0.136·φ^4.4/Swirr² with φ,Swirr in PERCENT -> mD."""
    s = 100.0 if percent else 1.0
    with np.errstate(invalid="ignore", divide="ignore"):
        k = c * (np.clip(phie, 0, 1) * s) ** phi_exp / np.clip(swirr * s, 1e-6, None) ** sw_exp
    return np.where(np.isfinite(k), np.clip(k, 0, None), np.nan)


def perm_coates(phie, swirr, c=10000.0):
    """Coates (free-fluid) k = C·(φ²·(1−Swirr)/Swirr)² with φ FRACTION. Reads higher
    than Timur in good rock; sensitive to Swirr."""
    with np.errstate(invalid="ignore", divide="ignore"):
        k = c * (np.clip(phie, 0, 1) ** 2 * (1.0 - swirr) / np.clip(swirr, 1e-3, None)) ** 2
    return np.where(np.isfinite(k), np.clip(k, 0, None), np.nan)


def perm_tixier(phie, swirr):
    """Tixier k = (250·φ³/Swirr)² with φ FRACTION."""
    with np.errstate(invalid="ignore", divide="ignore"):
        k = (250.0 * np.clip(phie, 0, 1) ** 3 / np.clip(swirr, 1e-3, None)) ** 2
    return np.where(np.isfinite(k), np.clip(k, 0, None), np.nan)


PERM_METHODS = {"timur": perm_timur, "coates": perm_coates, "tixier": perm_tixier}


# ============================ net pay helpers ============================

def triple_cutoff(vsh, phie, sw, vsh_cut=0.40, phie_cut=0.06, sw_cut=0.45, badhole=None):
    """Standard mechanical per-sample pay flag (matches the key's recipe). Returns a
    float 0/1 array; NaN inputs -> 0."""
    pay = (vsh <= vsh_cut) & (phie >= phie_cut) & (sw <= sw_cut)
    if badhole is not None:
        pay = pay & ~badhole
    pay = pay.astype(float)
    pay[~(np.isfinite(vsh) & np.isfinite(phie) & np.isfinite(sw))] = 0.0
    return pay


def apply_min_thickness(pay, depth, min_ft=1.0):
    """Jaccard-only filter: drop pay runs thinner than `min_ft`. RISKS diverging from
    the key's per-sample flagging — use only as a late A/B."""
    pay = pay.astype(float).copy()
    step = float(np.median(np.abs(np.diff(depth)))) if depth.size > 1 else 0.5
    on = pay > 0.5
    i = 0
    while i < on.size:
        if on[i]:
            j = i
            while j < on.size and on[j]:
                j += 1
            if (j - i) * step < min_ft - 1e-9:
                pay[i:j] = 0.0
            i = j
        else:
            i += 1
    return pay


# ============================ shale-property estimation ============================

def estimate_shale_props(vsh, rhob=None, nphi=None, rt=None, rho_ma=2.65, rho_fl=1.0,
                         shale_pct=85.0):
    """Read shale endpoints from the shaliest samples (Vsh ≥ `shale_pct` percentile):
    Rsh (shale resistivity), PHIDsh, NPHIsh, PHITsh. Feeds Simandoux/Indonesia SW and
    neutron-density / shale-subtraction PHIE. Returns a dict of scalars (NaN if absent)."""
    out = {"rsh": np.nan, "phid_sh": np.nan, "nphi_sh": np.nan, "phit_sh": np.nan}
    if vsh is None or not np.isfinite(vsh).any():
        return out
    thr = np.nanpercentile(vsh, shale_pct)
    sh = np.isfinite(vsh) & (vsh >= thr)
    if sh.sum() < 5:
        return out
    if rt is not None:
        v = rt[sh & np.isfinite(rt)]
        if v.size:
            out["rsh"] = float(np.median(v))
    if rhob is not None:
        v = rhob[sh & np.isfinite(rhob)]
        if v.size:
            out["phid_sh"] = float(np.median((rho_ma - v) / (rho_ma - rho_fl)))
    if nphi is not None:
        v = nphi[sh & np.isfinite(nphi)]
        if v.size:
            out["nphi_sh"] = float(np.median(v))
    if np.isfinite(out["phid_sh"]) and np.isfinite(out["nphi_sh"]):
        out["phit_sh"] = float(np.nanmean([out["phid_sh"], out["nphi_sh"]]))
    return out
