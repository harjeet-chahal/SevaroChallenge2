"""Benchmark: the official dataset through the full Detect → Decide → Act loop, with and
without voluntary availability ("I'm Available").

    cd backend && .venv/bin/python -m scripts.benchmark_voluntary --runs 100

The real FastAPI app runs in-process on a throwaway SQLite copy of the official dataset
(repo-root ``data/``). The simulation clock moves from 09:00 to 24:00 ET. A scripted
coordinator and clinical lead use the real endpoints (dashboard → propose → approve →
send), and scripted off-shift physicians answer offers through the real phone endpoint.
Nothing is shortcut: eligibility, offer limits, declines, expiry, activation and coverage
all come from the system.

Three arms, run on the same simulated days (common random numbers):

- ``normal``  — the pipeline without the feature (``voluntary.enabled = false``, no
  windows shared).
- ``feature`` — physicians share their availability window from the off-shift portal at
  the start of the day (``POST /api/availability``) and the optimizer uses it, exactly as
  shipped: a preference, so a volunteer can still be cold-offered outside their window.
- ``strict``  — WHAT-IF, not in the product: as ``feature``, plus one rule applied by the
  scripted coordinator: a physician who shared windows is not offered a shift outside
  them (the ranking card already shows that the window does not fit).

Ground truth (ASSUMPTION, identical in both arms; the dataset has no response data): each
opted-in off-shift physician is willing to pick up an extra shift today with probability
``willing``; a willing physician has one window, uniform start 09:00–20:00 on the half
hour, 4–8 h long. An offer is accepted only if it lies entirely inside that window (the
same "whole span" test the optimizer uses). A cold offer gets a reply within its 10 minutes
with probability ``reply_cold`` (1–9 min); otherwise it expires. In the feature arm, a
physician who shared a window answers an offer inside it with probability ``reply_vol``
(1–3 min): they asked to be contacted for exactly that time. Every other offer behaves as in
the normal arm. ``adoption`` is the share of willing physicians who use the portal.

Measured, not assumed: offers sent and their outcomes, proposals and approvals, API
requests, optimizer executions, CP-SAT solves and solver time, backend time, coverage gap
minutes (Phase 3 coverage engine) and paid split-shift minutes (cost policy, $200/h).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from multiprocessing import get_context
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[1]
DATA = BACKEND.parent / "data"
ET = ZoneInfo("America/New_York")
START = datetime(2026, 3, 17, 9, 0, tzinfo=ET)
END = datetime(2026, 3, 18, 0, 0, tzinfo=ET)
TICK = timedelta(minutes=5)
ARMS = ("normal", "feature", "strict")
COORD = {"X-Demo-Role": "coordinator", "X-Demo-Actor-Id": "coord-bench"}
LEAD = {"X-Demo-Role": "clinical_lead", "X-Demo-Actor-Id": "lead-bench"}


def doctor(pid: str) -> dict[str, str]:
    return {"X-Demo-Role": "physician", "X-Demo-Actor-Id": pid}


@dataclass(frozen=True)
class Params:
    willing: float = 0.6
    reply_cold: float = 0.7
    reply_vol: float = 0.95
    adoption: float = 1.0


# --------------------------------------------------------------- instrumentation --

PHASE = "setup"
"""Which part of the loop is running: monitor (dashboard refresh), workflow (propose,
approve, send, respond, clock sweep) or measure (benchmark-only coverage reading)."""


@dataclass
class Meter:
    staffing_runs: Counter = field(default_factory=Counter)
    staffing_ms: Counter = field(default_factory=Counter)
    cpsat_solves: Counter = field(default_factory=Counter)
    cpsat_stage_solves: Counter = field(default_factory=Counter)
    cpsat_ms: Counter = field(default_factory=Counter)
    voluntary_resolves: Counter = field(default_factory=Counter)
    analyses: Counter = field(default_factory=Counter)
    analysis_ms: Counter = field(default_factory=Counter)
    api_calls: Counter = field(default_factory=Counter)
    api_ms: Counter = field(default_factory=Counter)


METER = Meter()


def install_meters() -> None:
    """Wrap the optimizer entry points where the app looks them up (cache misses only)."""
    import app.engines.optimization.split_shift as split_shift
    import app.services.analysis as analysis_service
    import app.services.optimization as optimization_service

    real_run_staffing = optimization_service.run_staffing
    real_solve_cpsat = split_shift.solve_cpsat
    real_analyze = analysis_service.analyze

    def run_staffing(*args, **kwargs):
        started = time.perf_counter()
        try:
            return real_run_staffing(*args, **kwargs)
        finally:
            METER.staffing_runs[PHASE] += 1
            METER.staffing_ms[PHASE] += (time.perf_counter() - started) * 1000

    def solve_cpsat(ctx, options, voluntary=None):
        started = time.perf_counter()
        solution = real_solve_cpsat(ctx, options, voluntary)
        METER.cpsat_solves[PHASE] += 1
        METER.cpsat_ms[PHASE] += (time.perf_counter() - started) * 1000
        if solution is not None:
            METER.cpsat_stage_solves[PHASE] += len(solution.stages)
        if voluntary is not None:
            METER.voluntary_resolves[PHASE] += 1
        return solution

    def analyze(*args, **kwargs):
        started = time.perf_counter()
        try:
            return real_analyze(*args, **kwargs)
        finally:
            METER.analyses[PHASE] += 1
            METER.analysis_ms[PHASE] += (time.perf_counter() - started) * 1000

    optimization_service.run_staffing = run_staffing
    split_shift.solve_cpsat = solve_cpsat
    analysis_service.analyze = analyze


class Api:
    """TestClient wrapper that tags and times every request with the current phase."""

    def __init__(self, client) -> None:
        self.client = client

    def call(self, method: str, url: str, label: str, **kwargs):
        started = time.perf_counter()
        response = self.client.request(method, url, **kwargs)
        METER.api_calls[(PHASE, label)] += 1
        METER.api_ms[(PHASE, label)] += (time.perf_counter() - started) * 1000
        return response


# ------------------------------------------------------------------ ground truth --


@dataclass(frozen=True)
class Truth:
    windows: dict[str, tuple[datetime, datetime]]
    """Willing physicians and the window they would accept work in."""
    shares: frozenset[str]
    """Willing physicians who share their window in the feature arm."""


def sample_truth(seed: int, physicians: list[str], params: Params) -> Truth:
    windows: dict[str, tuple[datetime, datetime]] = {}
    shares: set[str] = set()
    for pid in physicians:
        rng = random.Random(f"truth-{seed}-{pid}")
        willing = rng.random() < params.willing
        start = START + timedelta(minutes=30 * rng.randrange(0, 23))  # 09:00 … 20:00
        hours = rng.choice([4, 5, 6, 7, 8])
        adopts = rng.random() < params.adoption
        if willing:
            windows[pid] = (start, min(start + timedelta(hours=hours), END))
            if adopts:
                shares.add(pid)
    return Truth(windows, frozenset(shares))


def response_for(
    seed: int,
    pid: str,
    k: int,
    start: datetime,
    end: datetime,
    truth: Truth,
    arm: str,
    params: Params,
) -> tuple[str, int]:
    """(accept | decline | none, minutes after sending) for the k-th offer to ``pid``. The
    draws depend only on (seed, physician, k), so both arms see the same luck."""
    rng = random.Random(f"reply-{seed}-{pid}-{k}")
    u_reply, u_delay = rng.random(), rng.random()
    window = truth.windows.get(pid)
    inside = window is not None and window[0] <= start and end <= window[1]
    if arm != "normal" and pid in truth.shares and inside:
        if u_reply < params.reply_vol:
            return "accept", 1 + int(u_delay * 3)
        return "none", 10
    if u_reply < params.reply_cold:
        return ("accept" if inside else "decline"), 1 + int(u_delay * 9)
    return "none", 10


# -------------------------------------------------------------------------- run --


def build_template(folder: Path) -> Path:
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    db = folder / "template.db"
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{db}",
        cors_origins="http://localhost:3000",
    )
    with TestClient(create_app(settings)) as client:
        files = [("files", (p.name, p.read_bytes())) for p in sorted(DATA.glob("*.csv"))]
        response = client.post("/api/datasets/import", files=files)
        assert response.status_code == 200, response.text
    return db


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def realized_deficit(analysis, until: datetime) -> dict[str, float]:
    """Physician-minutes short per hospital from ``as_of`` to ``until`` (coverage engine,
    accepted and active split shifts included through the workflow overlay)."""
    out: dict[str, float] = {}
    for hid, model in analysis.coverage_models.items():
        total = 0.0
        for a, b, e in model.evaluations():
            lo, hi = max(a, analysis.state.as_of), min(b, until)
            if hi > lo and e.deficit:
                total += e.deficit * (hi - lo).total_seconds() / 60
        out[hid] = total
    return out


def run_day(job: dict) -> dict:
    """One simulated day for one arm. Runs in a worker process."""
    global PHASE, METER
    METER = Meter()
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.core.config import Settings
    from app.db.session import build_engine
    from app.main import create_app
    from app.services.analysis import AnalysisCache, AnalysisService

    seed, arm, params = job["seed"], job["arm"], Params(**job["params"])
    work = Path(tempfile.mkdtemp(prefix="vbench-"))
    db = work / "run.db"
    shutil.copy(job["template"], db)
    policy = work / "policy.json"
    policy.write_text(json.dumps({"voluntary": {"enabled": arm != "normal"}}))
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{db}",
        cors_origins="http://localhost:3000",
        optimization_policy_file=policy,
    )
    engine = build_engine(settings.resolved_database_url)
    measure_cache = AnalysisCache(maxsize=2)

    offers: dict[str, dict] = {}
    pending: dict[str, tuple[datetime, str]] = {}  # offer_id -> (reply at, response)
    sent_count: Counter = Counter()
    episodes: dict[str, dict] = {}
    open_episode: dict[str, str] = {}
    refused: dict[tuple, str] = {}
    deficit_total: dict[str, float] = defaultdict(float)
    unaddressed_minutes = 0.0
    skipped_outside_window = 0
    log: list[str] = []

    with TestClient(create_app(settings)) as client:
        api = Api(client)
        PHASE = "setup"
        r = api.call("POST", "/api/simulation/time", "set_time", json={"time": _iso(START)})
        assert r.status_code == 200, r.text
        truth = sample_truth(seed, job["opted_in"], params)
        if arm != "normal":
            PHASE = "workflow"
            for pid in sorted(truth.shares):
                start, end = truth.windows[pid]
                r = api.call(
                    "POST",
                    "/api/availability",
                    "share_availability",
                    headers=doctor(pid),
                    json={"start_at": _iso(max(start, START)), "end_at": _iso(end)},
                )
                assert r.status_code == 201, r.text
        METER = Meter()  # setup is not part of either pipeline's daily cost

        now = START
        while now < END:
            # 1. Physicians answer the offers that are due (phone view).
            PHASE = "workflow"
            for oid, (at, response) in sorted(pending.items(), key=lambda kv: kv[1][0]):
                if at > now:
                    continue
                del pending[oid]
                if response == "none":
                    continue
                pid = offers[oid]["physician_id"]
                r = api.call(
                    "POST",
                    f"/api/offers/{oid}/respond",
                    "respond",
                    headers=doctor(pid),
                    json={"response": response},
                )
                if r.status_code == 200:
                    offers[oid]["outcome"] = r.json()["outcome"]
                    offers[oid]["responded_at"] = now
                    log.append(f"{now:%H:%M} {pid} {r.json()['outcome']} {oid}")

            # 2. Coordinator dashboard refresh.
            PHASE = "monitor"
            staffing = api.call("GET", "/api/optimization/split-shifts", "dashboard").json()
            gaps = list(staffing["gap_hospital_ids"])
            recs = staffing["recommendations"]

            for hid in gaps:
                if hid not in open_episode:
                    eid = f"{hid}@{now:%H:%M}"
                    open_episode[hid] = eid
                    episodes[eid] = {
                        "hospital": hid,
                        "detected": now,
                        "first_offer": None,
                        "filled": None,
                        "offers": 0,
                        "ended": None,
                    }
            for hid in list(open_episode):
                if hid not in gaps:
                    episodes[open_episode.pop(hid)]["ended"] = now

            # 3. Coordinator proposes the recommended split shift; clinical lead approves
            #    and sends it. One request per recommendation, primary physician only.
            PHASE = "workflow"
            busy = {o["physician_id"] for o in offers.values() if o["id"] in pending}
            for rec in recs:
                pid = rec["physician_id"]
                need = [h for h in rec["hospital_ids"] if h in gaps]
                if not need or pid in busy:
                    continue
                if arm == "strict" and pid in truth.shares:
                    lo, hi = truth.windows[pid]
                    start = datetime.fromisoformat(rec["offer_start"])
                    end = datetime.fromisoformat(rec["offer_end"])
                    if not (max(lo, START) <= start and end <= hi):
                        skipped_outside_window += 1
                        continue
                key = (pid, tuple(need), staffing["data_version"], len(offers))
                if key in refused:
                    continue
                r = api.call(
                    "POST",
                    "/api/interventions",
                    "propose",
                    headers=COORD,
                    json={"type": "split_shift", "hospital_ids": need, "physician_ids": [pid]},
                )
                if r.status_code != 201:
                    refused[key] = r.text[:300]
                    log.append(f"{now:%H:%M} refused {pid} {need}: {r.text[:300]}")
                    continue
                iid = r.json()["id"]
                r = api.call(
                    "POST",
                    f"/api/interventions/{iid}/decision",
                    "approve",
                    headers=LEAD,
                    json={"decision": "approve"},
                )
                if r.status_code != 200:
                    refused[key] = r.text[:300]
                    log.append(f"{now:%H:%M} refused {pid} {need}: {r.text[:300]}")
                    continue
                r = api.call(
                    "POST", f"/api/interventions/{iid}/send-offers", "send_offers", headers=LEAD
                )
                if r.status_code != 200:
                    refused[key] = r.text[:300]
                    log.append(f"{now:%H:%M} refused {pid} {need}: {r.text[:300]}")
                    continue
                for o in r.json()["offers"]:
                    if o["id"] in offers or o["status"] != "sent":
                        continue
                    o["hospital_ids"] = [h["id"] for h in o["hospitals"]]
                    start = datetime.fromisoformat(o["start_at"])
                    end = datetime.fromisoformat(o["end_at"])
                    k = sent_count[o["physician_id"]]
                    sent_count[o["physician_id"]] += 1
                    response, delay = response_for(
                        seed, o["physician_id"], k, start, end, truth, arm, params
                    )
                    offers[o["id"]] = {
                        "id": o["id"],
                        "physician_id": o["physician_id"],
                        "hospital_ids": o["hospital_ids"],
                        "start": start,
                        "end": end,
                        "minutes": o["duration_minutes"],
                        "minutes_to_online": o.get("minutes_to_online", 0),
                        "sent_at": now,
                        "inside_window": bool(
                            truth.windows.get(o["physician_id"])
                            and truth.windows[o["physician_id"]][0] <= start
                            and end <= truth.windows[o["physician_id"]][1]
                        ),
                        "outcome": "pending",
                    }
                    pending[o["id"]] = (now + timedelta(minutes=delay), response)
                    busy.add(o["physician_id"])
                    for h in o["hospital_ids"]:
                        eid = open_episode.get(h)
                        if eid:
                            episodes[eid]["offers"] += 1
                            episodes[eid]["first_offer"] = episodes[eid]["first_offer"] or now
                    log.append(
                        f"{now:%H:%M} offer {o['id']} → {o['physician_id']} "
                        f"{start.astimezone(ET):%H:%M}–{end.astimezone(ET):%H:%M} "
                        f"{','.join(o['hospital_ids'])} (will: {response} +{delay}m)"
                    )

            # 4. Benchmark-only: coverage gap until the next step (not counted as cost).
            next_tick = min(START + TICK * ((now - START) // TICK + 1), END)
            due = [at for at, _ in pending.values() if at > now]
            nxt = min([next_tick, *due])
            PHASE = "measure"
            with Session(engine) as session:
                analysis = AnalysisService(session, settings, measure_cache).analysis(None)
            short = realized_deficit(analysis, nxt)
            for hid, value in short.items():
                deficit_total[hid] += value
            for hid in gaps:
                if not any(
                    hid in o["hospital_ids"] and (oid in pending or o["outcome"] == "accepted")
                    for oid, o in offers.items()
                ):
                    unaddressed_minutes += (nxt - now).total_seconds() / 60

            # 5. Move the clock (the sweep expires offers and activates accepted shifts).
            PHASE = "workflow"
            r = api.call(
                "POST",
                "/api/simulation/advance",
                "advance_clock",
                json={"minutes": (nxt - now).total_seconds() / 60},
            )
            assert r.status_code == 200, r.text
            now = nxt

        PHASE = "measure"
        final = client.get("/api/offers", headers=COORD).json()["items"]
    engine.dispose()
    shutil.rmtree(work, ignore_errors=True)

    status = {o["id"]: o["status"] for o in final}
    for oid, o in offers.items():
        o["final_status"] = status.get(oid, "unknown")
    for o in offers.values():
        if o["final_status"] in ("accepted", "active", "completed"):
            for h in o["hospital_ids"]:
                for ep in episodes.values():
                    if (
                        ep["hospital"] == h
                        and ep["detected"] <= o["sent_at"]
                        and (ep["ended"] is None or o["sent_at"] <= ep["ended"])
                    ):
                        ep["filled"] = ep["filled"] or o.get("responded_at")
    paid = sum(
        o["minutes"]
        for o in offers.values()
        if o["final_status"] in ("accepted", "active", "completed")
    )
    outcomes = Counter(o["final_status"] for o in offers.values())

    def by_phase(counter: Counter) -> dict[str, float]:
        return {k: round(v, 3) for k, v in counter.items() if k != "measure"}

    return {
        "seed": seed,
        "arm": arm,
        "params": asdict(params),
        "truth": {
            pid: [w[0].astimezone(ET).strftime("%H:%M"), w[1].astimezone(ET).strftime("%H:%M")]
            for pid, w in truth.windows.items()
        },
        "shares": sorted(truth.shares),
        "offers_sent": len(offers),
        "offer_outcomes": dict(outcomes),
        "offers_inside_window": sum(o["inside_window"] for o in offers.values()),
        "accepted": sum(outcomes[s] for s in ("accepted", "active", "completed")),
        "wasted_offers": sum(outcomes[s] for s in ("declined", "expired")),
        "proposals": METER.api_calls[("workflow", "propose")],
        "approvals": METER.api_calls[("workflow", "approve")],
        "api_calls": {f"{p}:{label}": n for (p, label), n in METER.api_calls.items()},
        "api_ms": {f"{p}:{label}": round(v, 3) for (p, label), v in METER.api_ms.items()},
        "staffing_runs": by_phase(METER.staffing_runs),
        "staffing_ms": by_phase(METER.staffing_ms),
        "cpsat_solves": by_phase(METER.cpsat_solves),
        "cpsat_stage_solves": by_phase(METER.cpsat_stage_solves),
        "cpsat_ms": by_phase(METER.cpsat_ms),
        "voluntary_resolves": by_phase(METER.voluntary_resolves),
        "analyses": by_phase(METER.analyses),
        "analysis_ms": by_phase(METER.analysis_ms),
        "deficit_by_hospital": {h: round(v, 3) for h, v in deficit_total.items() if v},
        "deficit_total": round(sum(deficit_total.values()), 3),
        "unaddressed_gap_minutes": round(unaddressed_minutes, 3),
        "skipped_outside_window": skipped_outside_window,
        "paid_minutes": paid,
        "episodes": [
            {
                **{
                    k: v
                    for k, v in ep.items()
                    if k not in ("detected", "first_offer", "filled", "ended")
                },
                "detected": ep["detected"].astimezone(ET).strftime("%H:%M"),
                "minutes_to_fill": (ep["filled"] - ep["detected"]).total_seconds() / 60
                if ep["filled"]
                else None,
                "minutes_to_first_offer": (ep["first_offer"] - ep["detected"]).total_seconds() / 60
                if ep["first_offer"]
                else None,
            }
            for ep in episodes.values()
        ],
        "log": log,
    }


# ------------------------------------------------------------------------ report --


def mean(values) -> float:
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def summarize(rows: list[dict]) -> dict:
    def total(row, key, phases=("monitor", "workflow")):
        return sum(row[key].get(p, 0) for p in phases)

    api_workflow = [
        sum(
            n for k, n in r["api_calls"].items() if k.startswith("workflow:") and "advance" not in k
        )
        for r in rows
    ]
    filled = [ep for r in rows for ep in r["episodes"] if ep["minutes_to_fill"] is not None]
    actionable = [ep for r in rows for ep in r["episodes"] if ep["offers"]]
    return {
        "runs": len(rows),
        "offers_sent": mean(r["offers_sent"] for r in rows),
        "accepted": mean(r["accepted"] for r in rows),
        "wasted_offers": mean(r["wasted_offers"] for r in rows),
        "declined": mean(r["offer_outcomes"].get("declined", 0) for r in rows),
        "expired": mean(r["offer_outcomes"].get("expired", 0) for r in rows),
        "offers_per_acceptance": (
            sum(r["offers_sent"] for r in rows) / max(1, sum(r["accepted"] for r in rows))
        ),
        "proposals": mean(r["proposals"] for r in rows),
        "approvals": mean(r["approvals"] for r in rows),
        "workflow_api_calls": mean(api_workflow),
        "workflow_staffing_runs": mean(r["staffing_runs"].get("workflow", 0) for r in rows),
        "workflow_cpsat_solves": mean(r["cpsat_solves"].get("workflow", 0) for r in rows),
        "workflow_cpsat_stage_solves": mean(
            r["cpsat_stage_solves"].get("workflow", 0) for r in rows
        ),
        "workflow_staffing_ms": mean(r["staffing_ms"].get("workflow", 0) for r in rows),
        "workflow_backend_ms": mean(
            sum(
                v
                for k, v in r["api_ms"].items()
                if k.startswith("workflow:") and "advance" not in k
            )
            for r in rows
        ),
        "monitor_refreshes": mean(r["api_calls"].get("monitor:dashboard", 0) for r in rows),
        "monitor_staffing_runs": mean(r["staffing_runs"].get("monitor", 0) for r in rows),
        "monitor_cpsat_solves": mean(r["cpsat_solves"].get("monitor", 0) for r in rows),
        "monitor_staffing_ms": mean(r["staffing_ms"].get("monitor", 0) for r in rows),
        "monitor_voluntary_resolves": mean(r["voluntary_resolves"].get("monitor", 0) for r in rows),
        "all_staffing_runs": mean(total(r, "staffing_runs") for r in rows),
        "all_cpsat_solves": mean(total(r, "cpsat_solves") for r in rows),
        "all_cpsat_stage_solves": mean(total(r, "cpsat_stage_solves") for r in rows),
        "all_staffing_ms": mean(total(r, "staffing_ms") for r in rows),
        "all_backend_ms": mean(sum(r["api_ms"].values()) for r in rows),
        "deficit_total": mean(r["deficit_total"] for r in rows),
        "unaddressed_gap_minutes": mean(r["unaddressed_gap_minutes"] for r in rows),
        "skipped_outside_window": mean(r["skipped_outside_window"] for r in rows),
        "paid_minutes": mean(r["paid_minutes"] for r in rows),
        "minutes_to_fill": mean(ep["minutes_to_fill"] for ep in filled),
        "fill_rate": len(filled) / max(1, len(actionable)),
        "gaps_filled": mean(
            sum(ep["minutes_to_fill"] is not None for ep in r["episodes"]) for r in rows
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--willing", type=float, default=Params.willing)
    parser.add_argument("--reply-cold", type=float, default=Params.reply_cold)
    parser.add_argument("--reply-vol", type=float, default=Params.reply_vol)
    parser.add_argument("--adoption", type=float, default=Params.adoption)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--seed-offset", type=int, default=0)
    args = parser.parse_args()
    params = Params(args.willing, args.reply_cold, args.reply_vol, args.adoption)

    folder = Path(tempfile.mkdtemp(prefix="vbench-template-"))
    template = build_template(folder)
    with open(DATA / "physicians_off_shift_roster.csv", newline="") as handle:
        opted_in = sorted(
            row["physician_id"]
            for row in csv.DictReader(handle)
            if row["split_shift_opt_in"].strip().lower() == "yes"
        )
    jobs = [
        {
            "seed": args.seed_offset + s,
            "arm": arm,
            "params": asdict(params),
            "template": str(template),
            "opted_in": opted_in,
        }
        for s in range(args.runs)
        for arm in ARMS
    ]
    started = time.perf_counter()
    with ProcessPoolExecutor(
        max_workers=args.workers, mp_context=get_context("spawn"), initializer=install_meters
    ) as pool:
        rows = list(pool.map(run_day, jobs))
    shutil.rmtree(folder, ignore_errors=True)
    summary = {arm: summarize([r for r in rows if r["arm"] == arm]) for arm in ARMS}
    result = {
        "params": asdict(params),
        "runs": args.runs,
        "elapsed_s": round(time.perf_counter() - started, 1),
        "summary": summary,
        "rows": rows,
    }
    out = args.out or Path(tempfile.gettempdir()) / "voluntary_benchmark.json"
    out.write_text(json.dumps(result, indent=1, default=str))
    width = max(len(k) for k in summary["normal"])
    print(f"params {asdict(params)}  runs {args.runs}  elapsed {result['elapsed_s']} s")
    print(f"{'metric':<{width}}  {'normal':>10}  {'feature':>10} {'Δ':>6}  {'strict':>10} {'Δ':>6}")
    for key in summary["normal"]:
        a = summary["normal"][key]
        cells = []
        for arm in ARMS[1:]:
            b = summary[arm][key]
            change = f"{(b - a) / a * 100:+.0f}%" if a else ""
            cells.append(f"{b:>10.2f} {change:>6}")
        print(f"{key:<{width}}  {a:>10.2f}  " + "  ".join(cells))
    print(f"wrote {out}")


if __name__ == "__main__":
    sys.path.insert(0, str(BACKEND))
    main()
