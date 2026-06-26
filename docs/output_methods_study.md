# Output Methods Study — how each curve can be calculated from OUR 800 LAS

For each submission curve (VSH, PHIT, PHIE, SW, PERM, PAY_FLAG): the menu of
calculation methods, **filtered to only those computable from the inputs actually
present in this dataset** (curves + `~Params` metadata). Methods that need data we
don't have (core, CEC, formation tops) are listed once at the end as excluded.

```
GR ───────────────────────────► VSH ──┐
                                       ├──► PHIE ──┬──► SW ──┐
RHOB ──► PHID ─┐                       │           │        ├──► PAY_FLAG
NPHI ──► PHIN ─┴──► PHIT ──────────────┘           │        │
SONIC ─► PHIS (gap-fill PHID only)                 └──► PERM ┘
RES_DEEP ──────────────────────────────────► SW
metadata(BHT,RMF,RMFT,MUD) ──► Rw, T ───────► SW
```

## Available inputs (verified across the 800 wells)
| Input | Coverage | Enables |
|---|---|---|
| GR | 100% | VSH |
| RHOB, NPHI | 100% each | PHID, PHIN, PHIT, DN-VSH |
| SONIC (compressional Δt) | 100% | sonic porosity |
| PEF | 100% | matrix/lithology for porosity |
| CAL + BHS (bit size) | 100% | bad-hole mask |
| SP | 100% (valid on the 600 WBM wells; OBM suppresses SP) | SP-VSH, SP-Rw |
| RES_DEEP (Rt) | 100% | SW (Archie etc.) |
| RES_SHAL (Rxo) | 100% | Rxo/Rt SW, invasion |
| RES_MED | 44% | medium-Rt only |
| `~Params`: BHT, RMF, RMFT, RM, RMT, MW, MUD | 100% each | Rw (Rmf@formation-T), temperature |
| `rmf_formation_temp` (Arps-corrected Rmf) | 100% (precomputed) | per-well Rw prior |
| **NOT present:** core, CEC/Qv, formation tops, fluid contacts, shear sonic (DTS ~0%), DRHO (6%) | — | — (see Excluded) |

---

## VSH — shale volume
Inputs available: GR (100%), RHOB+NPHI (100%), SP (100%, valid on WBM).

Computable methods (`IGR = (GR−GRcl)/(GRsh−GRcl)`):
- **GR linear** `Vsh = IGR` — *current default*.
- **Larionov (Tertiary)** `Vsh = 0.083·(2^(3.7·IGR) − 1)`.
- **Larionov (older rocks)** `Vsh = 0.33·(2^(2·IGR) − 1)`.
- **Clavier** `Vsh = 1.7 − √(3.38 − (IGR + 0.7)²)`.
- **Stieber** `Vsh = IGR / (3 − 2·IGR)`.
- **Neutron–density** `Vsh = (NPHI − PHID) / (NPHIsh − PHIDsh)` (shale points read from a shale bed).
- **SP** `Vsh = 1 − (PSP/SSP)` from SP reduction vs the clean-sand SSP — **WBM wells only (600)**.
- **Minimum-of-indicators** `Vsh = min(VshGR, VshND, VshSP)`.

---

## PHIT — total porosity
Inputs available: RHOB (100%), NPHI (100%), SONIC (100%), PEF (100% for matrix).

Computable methods:
- **Density porosity** `PHID = (ρma − ρb)/(ρma − ρfl)`.
- **Neutron porosity** `PHIN = NPHI` (matrix-referenced).
- **Density–neutron average** `(PHID + PHIN)/2` — *current default*.
- **Density–neutron RMS** `√((PHID² + PHIN²)/2)` (gas-leaning combine).
- **Gas-corrected DN** (density-weighted where NPHI<PHID).
- **Sonic — Wyllie** `PHIS = (Δt − Δtma)/(Δtfl − Δtma)` (*current gap-fill*).
- **Sonic — Raymer-Hunt-Gardner** `φ = 0.625·(1 − Δtma/Δt)`.
- **DN crossplot apparent porosity** (lithology set by PEF).

---

## PHIE — effective porosity  **(Axis-4 scored, τ=0.03)**
Inputs available: PHIT and VSH (both derived above).

Computable methods:
- **`PHIT·(1 − Vsh)`** — *current default*.
- **`PHIT − Vsh·PHITsh`** — subtract the shale's own porosity (`PHITsh` read from a shale bed).
- **DN shale-corrected** `PHIDc = PHID − Vsh·PHIDsh`, `PHINc = NPHI − Vsh·NPHIsh`, then combine.
- **Thomas–Stieber** (laminated shaly sand) — effective porosity from the NPHI-vs-Vsh trend
  (computable from NPHI + Vsh; no extra curves needed).

---

## SW — water saturation  **(Axis-4 scored, τ=0.10)**
Inputs available: RES_DEEP/Rt (100%), RES_SHAL/Rxo (100%), RES_MED (44%), PHIE, and Rw inputs.

Computable saturation methods:
- **Archie** `Sw = ((a·Rw)/(PHIE^m·Rt))^(1/n)` — *current* (clean-sand).
- **Simandoux** `1/Rt = (PHIE^m/(a·Rw))·Sw^n + (Vsh/Rsh)·Sw` → solve Sw (needs Vsh, Rsh from a shale bed).
- **Modified Simandoux / Indonesia (Poupon-Leveaux)** — shaly-sand, same inputs (Vsh, Rsh, Rw).
- **Dual-water** — needs clay-bound-water `Swb`, approximated from `Vsh` and shale porosity (model-heavy but computable, no core).
- **Rxo/Rt (moved-hydrocarbon)** `Sw/Sxo = (Rxo/Rt · Rw/Rmf)^(1/n)` using Rxo=RES_SHAL + Rmf metadata.

Computable Rw sources (feed all of the above):
- **Pickett plot** — from Rt vs PHIE in clean wet sands → Rw (intercept) and m (slope).
- **SP–SSP** `SSP = −K·log(Rmfe/Rwe)`, K from BHT, Rmf from `~Params` — **WBM only (600 wells)**.
- **Rmf @ formation-T** — `rmf_formation_temp` (Arps-corrected; precomputed on all 800) as a prior.

---

## PERM — permeability  **(Axis-4 scored, τ=0.5 log-decade)**
Inputs available: PHIE, and Swirr (from SW / bulk-volume-water). Submit linear mD.

Computable methods (φ–Swirr transforms; **percent** porosity per Timur convention):
- **Timur** `k = 0.136·φ^4.4 / Swirr²` — *current*.
- **Coates** `k = ((φ·100)²·(1 − Swirr)/Swirr)²·C`.
- **Tixier** `k = (250·φ³/Swirr)²`.
- **Wyllie–Rose** `k = (C·φ^a / Swirr^b)` (generic φ–Swirr form).

Computable Swirr source: **bulk-volume-water** `BVW = PHIE·SW` held constant across clean pay
(irreducible-Sw floor); set as `ov_swirr_floor`.

---

## PAY_FLAG — net pay  **(Axis-2 footage+Jaccard, Axis-3 honeypot)**
Inputs available: VSH, PHIE, SW (derived), Rt profile, PEF.

Computable methods:
- **Triple cutoff** `Vsh < c1 & PHIE > c2 & SW < c3` — *current* (c = 0.40 / 0.06 / 0.45).
- **Cutoff + thickness/contiguity** filter (drop sub-foot stringers).
- **Fluid-contact-aware** — stop pay below an OWC *inferred* from a deep-resistivity drop at
  constant porosity (no contacts are given; must be read from the Rt profile).
- **Lithology/facies-gated** — restrict pay to reservoir facies via PEF + DN.

---

## Excluded — methods that need data this dataset does not contain
| Method | Output | Missing input |
|---|---|---|
| Waxman–Smits | SW | CEC / Qv (core measurement) |
| Winland R35, FZI / flow-units, Lucia rock-typing | PERM | core poro-perm |
| Calibrated poro-perm regression | PERM | core permeability |
| Direct fluid-contact pay cutoff | PAY_FLAG | no formation tops / OWC supplied (only inferable from Rt) |
| Vp/Vs or shear-based porosity/mechanics | PHIT | shear sonic essentially absent (~0%) |
| DRHO-based density quality correction | PHIT | DRHO present on only 6% of wells |
