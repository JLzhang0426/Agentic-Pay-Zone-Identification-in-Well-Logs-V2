"""
Run ledger + score-feedback loop for "No Second Guessing".

Two records, two scopes:
  - provenance.csv / final_provenance.csv  = per-WELL audit (what was decided for
    each well: roles, Rw, honeypot, gates).
  - THIS ledger                            = per-RUN record (every global
    assumption + the agent's deviations + the leaderboard score it earned).

The point: trace each submission's score back to the exact assumptions, so the
agent can tell which assumption to change next.

Files (under runs/):
  runs/<run_id>/manifest.json   full snapshot of one run (assumptions, overrides,
                                stats, and a score block to fill after submitting)
  runs/<run_id>/decisions.csv   copy of the decisions used (reproducibility)
  runs/scoreboard.csv           one row per run; the at-a-glance A/B history

After you submit and get a score:
  python preprocessing/run_ledger.py record <run_id> --public S
         --a1 .. --a2 .. --a3 .. --a4 .. --notes "..."
"""
from __future__ import annotations
import csv, glob, json, os, shutil, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNS = os.path.join(ROOT, "runs")
SCOREBOARD = os.path.join(RUNS, "scoreboard.csv")
SB_COLS = ["run_id", "timestamp", "hypothesis", "honeypot_count", "n_recomputed",
           "n_override", "n_pay", "avg_gate", "public_score", "A1", "A2", "A3",
           "A4", "delta_vs_prev", "notes"]


def new_run_id() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def agent_deviations(decisions_path: str) -> list[dict]:
    """Rows where the agent departed from the deterministic reference."""
    out = []
    if not os.path.exists(decisions_path):
        return out
    ovcols = ["ov_gr_clean", "ov_gr_shale", "ov_vsh_cut", "ov_phie_cut", "ov_sw_cut", "ov_rw"]
    for r in csv.DictReader(open(decisions_path)):
        ov = {c: r[c] for c in ovcols if (r.get(c) or "").strip()}
        changed = (r.get("honeypot") != r.get("honeypot_ref")
                   or (r.get("pay_action") or "accept") != "accept" or ov)
        if changed:
            out.append(dict(well_id=r["well_id"], honeypot=r.get("honeypot"),
                            honeypot_ref=r.get("honeypot_ref"),
                            pay_action=r.get("pay_action"), overrides=ov,
                            notes=r.get("notes", "")))
    return out


def write_run(assumptions: dict, stats: dict, decisions_path: str,
              hypothesis: str = "", run_id: str | None = None) -> str:
    run_id = run_id or new_run_id()
    rdir = os.path.join(RUNS, run_id)
    os.makedirs(rdir, exist_ok=True)
    devs = agent_deviations(decisions_path)
    manifest = dict(
        run_id=run_id, timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        hypothesis=hypothesis,
        assumptions=assumptions,
        agent_deviations=devs, n_agent_deviations=len(devs),
        stats=stats,
        score=dict(public=None, private=None, A1=None, A2=None, A3=None, A4=None,
                   recorded_at=None, notes=""),
    )
    with open(os.path.join(rdir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    if os.path.exists(decisions_path):
        shutil.copy(decisions_path, os.path.join(rdir, "decisions.csv"))
    _append_scoreboard(dict(
        run_id=run_id, timestamp=manifest["timestamp"], hypothesis=hypothesis,
        honeypot_count=stats.get("n_honeypot", ""), n_recomputed=stats.get("n_recomputed", ""),
        n_override=stats.get("n_override", ""), n_pay=stats.get("n_pay", ""),
        avg_gate=stats.get("avg_gate", ""), public_score="", A1="", A2="", A3="",
        A4="", delta_vs_prev="", notes=""))
    print(f"[run_ledger] recorded run {run_id} "
          f"({len(devs)} agent deviations) -> runs/{run_id}/manifest.json")
    return run_id


def _append_scoreboard(row: dict):
    os.makedirs(RUNS, exist_ok=True)
    new = not os.path.exists(SCOREBOARD)
    with open(SCOREBOARD, "a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=SB_COLS)
        if new: wr.writeheader()
        wr.writerow({k: row.get(k, "") for k in SB_COLS})


def record_score(run_id, public=None, a=None, notes=""):
    """Fill the leaderboard score for a run + compute delta vs the previous
    scored run, in both the manifest and the scoreboard."""
    a = a or {}
    mpath = os.path.join(RUNS, run_id, "manifest.json")
    if not os.path.exists(mpath):
        sys.exit(f"no run {run_id}")
    man = json.load(open(mpath))
    man["score"].update(public=public, A1=a.get("A1"), A2=a.get("A2"),
                        A3=a.get("A3"), A4=a.get("A4"),
                        recorded_at=datetime.datetime.now().isoformat(timespec="seconds"),
                        notes=notes)
    json.dump(man, open(mpath, "w"), indent=2)

    rows = list(csv.DictReader(open(SCOREBOARD))) if os.path.exists(SCOREBOARD) else []
    prev = [r for r in rows if r["run_id"] != run_id and r.get("public_score")]
    delta = ""
    if public is not None and prev:
        try: delta = round(float(public) - float(prev[-1]["public_score"]), 3)
        except ValueError: delta = ""
    for r in rows:
        if r["run_id"] == run_id:
            r.update(public_score=public if public is not None else "",
                     A1=a.get("A1", ""), A2=a.get("A2", ""), A3=a.get("A3", ""),
                     A4=a.get("A4", ""), delta_vs_prev=delta, notes=notes)
    with open(SCOREBOARD, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=SB_COLS); wr.writeheader(); wr.writerows(rows)
    print(f"[run_ledger] run {run_id}: public={public} delta_vs_prev={delta}")
    print("  -> compare runs/scoreboard.csv to decide the next assumption to change.")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "record":
        rid = sys.argv[2]
        def g(flag):
            return float(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else None
        notes = sys.argv[sys.argv.index("--notes") + 1] if "--notes" in sys.argv else ""
        record_score(rid, public=g("--public"),
                     a={"A1": g("--a1"), "A2": g("--a2"), "A3": g("--a3"), "A4": g("--a4")},
                     notes=notes)
    else:
        print(__doc__)
