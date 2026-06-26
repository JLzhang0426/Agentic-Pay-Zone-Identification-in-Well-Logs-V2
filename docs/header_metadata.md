# LAS Header Analysis — 800 Wells

Parsed from all 800 raw `.las` headers. Two parts: (A) every curve-information
variable, and (B/C) the useful `~Well` and `~Params` metadata.

## Part A — Curve information variables

**219 distinct curve mnemonics** across the dataset; 10–22 curves/well
(median 13). Grouped by canonical family (raw mnemonic = instance count):

| Family | Variants | Total | Raw mnemonics (count) |
|---|---|---|---|
| **DEPTH** | 7 | 800 | DEPT(293), DEPTH(227), MD(115), TDEP(60), DEPH(47), DEP(33), MDEPTH(25) |
| **GR** (gamma) | 23 | 962 | GR(185), SGR(93), ECGR(71), CGR(65), GRD(57), HSGR(52), GRGC(40), GRS(39), GR_EDTC(37), GKUT(34), GR1(30), GRR(30), NGRT(29), GRAM(28), HGR(27)… |
| **RHOB** (density) | 21 | 943 | RHOB(185), RHOZ(125), ZDEN(86), DEN(58), RHOB_CDL(48), DENS(44), ZDNC(41), HDRA(34), HDEN(33), FDC(31), RHOBC(30), DENB(30), DENC(28)… |
| **NPHI** (neutron/poro) | 24 | 954 | NPHI(132), TNPH(100), NPOR(72), HNPO(50), CNL(48), APLC(44), NEU(42), BPHI(42), CNCF(36), NEUT(36), PHIN(31), PHIS(26)… |
| **SONIC** | 23 | 945 | DTCO(119), DT(116), DTC(87), SONIC(64), AC(58), BHC(51), DTLN(51), SON(37), EDTC(35), HDTC(35), DT1R(34)… |
| **PEF** | 18 | 973 | PEF(189), PE(188), PEFZ(108), PEFA(81), HDPE(57), PPEN(35), HPEF(34), PE_CDL(32), PEF8(29), PEZ(28)… |
| **CALIPER** | 21 | 970 | CAL(173), CALI(146), HCAL(97), CALS(57), DCAL(53), LCAL(48), CAL_CDL(42), CAL1(40), CALDC(36), TAB(35)… |
| **SP** | 13 | 968 | SP(310), SSP(185), SPONT(91), SP_MV(79), SPC(50), SPR(46), PSP(42), SPM(32), SPHI(31), SPONPOT(30)… |
| **RES_DEEP** (Rt) | 25 | 1198 | ILD(115), LLD(71), RT(64), RB(63), AHF90(60), A16H(59), AHT90(59), AT90(58), RILD(57), A28H(56), P16H(55), A34H(55), RESD(53), RD(52)… |
| **RES_MED** | 14 | 597 | SFL(86), SFLU(68), LLS(48), HDRS(48), HMRS(47), RLA1(41), RS(37), HMIN(36), RILM(36), RSFL(35)… |
| **RES_SHAL** (Rxo) | 10 | 528 | RXO(146), MSFL(109), RXOZ(95), MLL(37), MCFL(37), SN(28), RMLL(25)… |
| **AUX** (non-petro) | 20 | 1104 | HAZI(72), WOB(69), TORQ(64), X2(62), SWOB(60), PRES(60), BSAL(59), DEVI(57), TEMP(56), UNKNOWN(55), BS(54), TENS(52), DRHO(51), ECD(51), RPM(50), MUDW(50), X1(48), ROP(46), TT1(45), TT2(43) |

RES_DEEP has the most instances (1198) because wells often carry multiple
array-induction deep curves (A16H/A22H/A28H/A34H = different spacings).
Units are unreliable across all families — normalize by value, not label.

## Part B — Useful `~Well` metadata

| Field | Populated | Useful? | Notes |
|---|---|---|---|
| **STRT / STOP / STEP** | 100% | ✅ essential | depth frame; STEP = 0.5 ft on 798/800 |
| **NULL** | 100% | ✅ essential | missing-value sentinel (−999.25) → convert to NaN |
| DATE | 100% | ◻ minor | log vintage (numeric YYYYMMDD-ish) |
| WELL / FLD / LOC / CNTY / STAT | 69–100% | ❌ unreliable | **synthetic / internally inconsistent** identity (e.g. name "NorthSea" + county "Reeves,TX" + PLSS "T27N R78W" Wyoming). Do not use for geology. |
| SRVC / COMP / UWI / API | 88–100% | ❌ | service co. / operator / IDs — scrambled, no geological value |

→ From `~Well`, only the **depth frame (STRT/STOP/STEP) and NULL** are useful.

## Part C — Useful `~Params` metadata  (the valuable block)

**Every well (100%) carries a complete mud + temperature suite** — this enables
a real Rw and temperature-corrected resistivity for every well:

| Param | Populated | p10 / p50 / p90 | Meaning / use |
|---|---|---|---|
| **BHT** | 100% | 71 / 165 / 207 | bottom-hole temperature → temp-correct Rt & Rw. Mixed °F (652) / °C (148, `BHT_UNIT=DEGC`) |
| **RMF** | 100% | 0.071 / 0.26 / 0.46 | mud-filtrate resistivity (Ω·m) → **derive Rw** (with SP) |
| **RMFT** | 100% | 81 / 126 / 168 | temperature at which RMF measured (°F) |
| **RM** | 100% | 0.90 / 2.64 / 4.53 | mud resistivity (Ω·m) |
| **RMT** | 100% | 73 / 86 / 96 | temperature at which RM measured (°F) |
| **MW** | 100% | 10 / 10.25 / 11 | mud weight; mixed ppg / KG/M3 (176 wells, `MW_UNIT`) |
| **BHS** | 100% | 8.5 / 8.5 / 8.75 | bit size (in) → bad-hole QC vs caliper |
| **MUD** | 100% | — | mud type: **WBM 600 / OBM 200 (exactly 75/25)** — affects SP & resistivity; the 25% share coincides with the honeypot fraction (lead to test) |

### Why this matters
- **Rw per well**: with RMF + RMFT + BHT (temperature gradient) + the SP curve,
  solve the SP equation `SSP = −K·log(Rmf_eq/Rw_eq)` for **Rw** — replacing the
  assumed 0.05 Ω·m. Directly improves **SW** (Axis-4 scored).
- **Temperature correction**: BHT gives a gradient to correct Rt and Rmf to
  formation temperature (Arps: `R₂=R₁(T₁+6.77)/(T₂+6.77)`, °F).
- **Bad-hole QC**: BHS vs caliper flags washouts (unreliable RHOB).
- **MUD=OBM**: oil-based mud suppresses SP and invades differently — worth a flag,
  and the exact 200/800 split is a lead worth cross-checking against honeypots.

### Units caution
BHT and MW appear in mixed units (°F/°C, ppg/KG·m⁻³), sometimes signalled by
sidecar `BHT_UNIT` / `MW_UNIT` params (present on ~18–22% of wells). Infer by
value magnitude when the unit tag is absent.

## Part D — Recommended extraction (the useful subset)

Per well, extract and store: `STRT, STOP, STEP, NULL, DATE, BHT(+unit), RMF,
RMFT, RM, RMT, MW(+unit), BHS, MUD`. Drop all `~Well` identity fields (synthetic).
This metadata feeds: Rw estimation, temperature correction, bad-hole QC, and the
MUD-type lead.
