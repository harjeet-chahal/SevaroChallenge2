"""Phase 4 end to end on the scripted ``synthetic_staffing`` sample.

Expected values are worked out by hand from scripts/generate_staffing_dataset.py
(reference time 2031-04-08 21:00Z), not copied from engine output:

Dispatch — Ada (P1): 5 consults, 2 open notes, last call 40 min ago -> cost
5·20 + 2·15 + 0 (low volume) + (50 − 40) = 140. Di (P4): 7 consults -> 7·20 + 200 (not low
volume) + (50 − 30) = 360. Ed (P5): 4 consults, last call 25 min ago -> 80 + 25 = 105.
Only Ada can take stroke STF-C1 (Bo is on video), so the optimum is C1→Ada, C2→Di,
C3→Ed (already ringing); STF-C4 has nobody (Bo on video, Cy ended a call 1 min ago).
Least-loaded routing in arrival order gives C2 (earlier) to Ada and strands C1.

Staffing (240-min window 21:00–01:00Z) — H1 short 22:00–23:00 and 00:00–01:00 (120),
H2 short 00:00–01:00 (60), H3 short 22:15–22:30 (15; Jo's night shift from 22:30) = 195.
Gil (P7, online 15 min, credentialed H1/H3) covering 22:00–01:00 needs start ≤ 21:45 and
end ≥ 01:00: 21:00+240 (excess 315) or 21:45+240 (excess 225) -> 21:45Z for 240 min,
leaving H2's 60. Over the 90-min dashboard horizon: H1 30 → 0, H3 15 → 0.
Shortage look-ahead (90 min, 21:00–22:30Z): H1 (from 22:00) and H3 (from 22:15) are short;
H2's gap starts at 00:00Z, 180 min ahead, so it is reported as a later gap and not acted on
yet. Mo (P12, credentialed only at H2) therefore also fails credentialing.
"""

from __future__ import annotations

import json

import pytest

from app.engines.optimization.routing import solve as routing_solve
from app.engines.optimization.split_shift import cpsat

BASE = "/api/optimization"
REF = "2031-04-08T21:00:00Z"


@pytest.fixture
def staffing(client):
    response = client.post("/api/datasets/sample", params={"name": "synthetic_staffing"})
    assert response.status_code == 200, response.text
    return client


def _get(client, path, **params):
    response = client.get(f"{BASE}/{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _metric(section, name):
    return next(m for m in section["metrics"] if m["metric"] == name)


# Dispatch ---------------------------------------------------------------------------


def test_dispatch_matches_hand_calculation(staffing):
    result = _get(staffing, "assignments")
    recs = {r["consult_id"]: r for r in result["plan"]["recommendations"]}

    assert result["as_of"].startswith("2031-04-08T21:00:00")
    assert {c: (r["physician_id"], r["kind"], r["edge_cost"]) for c, r in recs.items()} == {
        "STF-C1": ("STF-P1", "assign", 140),
        "STF-C2": ("STF-P4", "assign", 360),
        "STF-C3": ("STF-P5", "confirm_ringing", 105),
    }
    assert [r["consult_id"] for r in sorted(recs.values(), key=lambda r: r["priority"])] == [
        "STF-C1",
        "STF-C2",
        "STF-C3",
    ]
    assert recs["STF-C1"]["urgency_label"] == "critical alert · stroke"
    assert all(r["executed"] is False for r in recs.values())
    assert recs["STF-C1"]["workload"]["consults_this_shift_after"] == 6
    (c4,) = result["plan"]["unassigned"]
    assert c4["consult_id"] == "STF-C4" and c4["reason_code"] == "no_eligible_physician"
    reasons = {x["physician_id"]: " ".join(x["reasons"]) for x in c4["excluded"]}
    assert "video" in reasons["STF-P2"] and "1.0 min ago" in reasons["STF-P3"]
    assert result["solver"]["solver"] == "ortools.SimpleMinCostFlow"
    assert result["solver"]["status"] == "OPTIMAL" and result["solver"]["proven_optimal"]


def test_dispatch_separates_coverage_from_routing(staffing):
    rows = {p["physician_id"]: p for p in _get(staffing, "assignments")["physicians"]}

    assert rows["STF-P2"]["counts_for_coverage"] and not rows["STF-P2"]["eligible_for_dispatch"]
    assert rows["STF-P3"]["effective_routing_capacity"] == 0
    assert [c["code"] for c in rows["STF-P3"]["checks"] if not c["passed"]] == ["call_cooldown"]
    assert rows["STF-P5"]["effective_routing_capacity"] == 0  # reserved for the ringing call
    assert rows["STF-P1"]["open_async_consults"] == 2
    assert rows["STF-P1"]["effective_routing_capacity"] == 1


def test_assigned_consults_are_skipped_not_moved(staffing):
    skipped = {s["consult_id"] for s in _get(staffing, "assignments")["skipped"]}
    assert skipped == {"STF-C5", "STF-C6", "STF-C9", "STF-C10"}


# Staffing ---------------------------------------------------------------------------


def test_split_shift_candidates_each_fail_exactly_the_scripted_rule(staffing):
    result = _get(staffing, "split-shifts")
    rows = {c["physician_id"]: c for c in result["candidates"]}

    assert result["gap_hospital_ids"] == ["STF-H1", "STF-H3"]
    assert list(rows) == [f"STF-P{n}" for n in range(6, 13)]
    assert {pid: r["failed_rules"] for pid, r in rows.items()} == {
        "STF-P6": ["opt_in"],
        "STF-P7": [],
        "STF-P8": ["rest_10h"],
        "STF-P9": ["weekly_hours"],
        "STF-P10": ["no_overlap"],
        "STF-P11": ["credentialed_at_gap"],
        "STF-P12": ["credentialed_at_gap", "rest_10h"],
    }
    assert [pid for pid, r in rows.items() if r["eligible"]] == ["STF-P7"]
    rest = next(c for c in rows["STF-P12"]["checks"] if c["code"] == "rest_10h")
    assert rest["missing_data"] is True
    assert rows["STF-P9"]["remaining_weekly_hours"] == 1
    assert rows["STF-P7"]["gap_hospital_ids"] == ["STF-H1", "STF-H3"]


def test_split_shift_plan_matches_hand_calculation(staffing):
    result = _get(staffing, "split-shifts")
    (rec,) = result["recommendations"]
    totals = result["totals"]

    assert rec["physician_id"] == "STF-P7"
    assert rec["offer_start"].startswith("2031-04-08T21:45:00")
    assert rec["online_at"].startswith("2031-04-08T22:00:00")
    assert rec["offer_minutes"] == 240 and rec["hospital_ids"] == ["STF-H1", "STF-H3"]
    assert (
        totals["deficit_physician_minutes_before"],
        totals["deficit_physician_minutes_after"],
    ) == (
        195,
        60,
    )
    assert totals["excess_physician_minutes"] == 225 and totals["physicians_used"] == 1
    dashboard = {
        e["hospital_id"]: (
            e["deficit_physician_minutes_before"],
            e["deficit_physician_minutes_after"],
        )
        for e in rec["effects"]
        if e["horizon_minutes"] == 90
    }
    assert dashboard == {"STF-H1": (30, 0), "STF-H3": (15, 0)}
    assert rec["status"] == "proposed" and rec["requires_approval"] is True
    assert result["solver"]["status"] == "OPTIMAL" and result["solver"]["proven_optimal"]
    assert result["infeasibility"] == []  # H1 and H3 fully covered; H2 is not short yet
    assert any(
        "not acted on yet" in line and "Prairie Sample Medical from 19:00 CDT" in line
        for line in result["explanations"]
    )


def test_trap_protection_on_the_sample(staffing):
    result = _get(staffing, "split-shifts")
    protection = result["recommendations"][0]["protection"]
    trap = result["trap"]

    assert protection["routing_scope_hospital_ids"] == ["STF-H1", "STF-H3"]
    assert protection["excluded_credentialed_hospital_ids"] == ["STF-H4"]
    assert protection["seeded_consult_count"] == 6  # median of Ada 5, Bo 6, Di 7
    # Baseline means over 22:00–00:00Z: H1 1/h -> 2, H3 0.5/h -> 1, H4 4/h -> 8.
    arrivals = {h: v["arrivals"] for h, v in trap["unrestricted"]["by_hospital"].items()}
    assert arrivals == {"STF-H1": 2, "STF-H3": 1, "STF-H4": 8}
    assert trap["unrestricted"]["routed_to_joiner_elsewhere"] > 0
    assert trap["protected"]["routed_to_joiner_elsewhere"] == 0


# Comparison -------------------------------------------------------------------------


def test_comparison_reports_wins_ties_and_losses_honestly(staffing):
    comp = _get(staffing, "comparison")
    d, s = comp["dispatch"], comp["staffing"]

    assert (_metric(d, "assigned")["baseline"], _metric(d, "assigned")["optimized"]) == (2, 3)
    assert _metric(d, "urgent_unassigned")["baseline"] == 2
    assert _metric(d, "urgent_unassigned")["optimized"] == 1
    assert _metric(d, "max_workload")["outcome"] == "baseline_better"  # Di goes 7 -> 8
    assert _metric(d, "constraint_violations")["baseline"] == 0
    assert _metric(d, "constraint_violations")["outcome"] == "tie"
    assert _metric(d, "coverage_gap_pm")["outcome"] == "tie"
    assert _metric(d, "objective_cost")["outcome"] == "optimized_better"
    assert "worse on" in d["summary"]
    assert _metric(s, "deficit_after")["outcome"] == "tie"
    assert (
        _metric(s, "offered_minutes")["baseline"],
        _metric(s, "offered_minutes")["optimized"],
    ) == (
        360,
        240,
    )
    assert (_metric(s, "excess_pm")["baseline"], _metric(s, "excess_pm")["optimized"]) == (315, 225)
    assert comp["trap"] is not None
    assert {x["optimizer"] for x in comp["solvers"]} == {"dispatch", "staffing"}


# What-if ----------------------------------------------------------------------------


def test_simulate_projects_without_writing_anything(staffing):
    coverage_before = staffing.get("/api/coverage").json()
    events_before = staffing.get("/api/events", params={"limit": 1}).json()["total"]
    body = {
        "action": {
            "kind": "split_shift",
            "physician_id": "STF-P7",
            "start": "2031-04-08T21:45:00Z",
            "duration_minutes": 240,
        }
    }
    response = staffing.post(f"{BASE}/simulate", json=body)
    result = response.json()

    assert response.status_code == 200, response.text
    assert result["allowed"] and result["label"].startswith("Projected if accepted")
    assert {
        p["hospital_id"]: (
            p["deficit_physician_minutes_before"],
            p["deficit_physician_minutes_after"],
        )
        for p in result["projections"]
    } == {"STF-H1": (30, 0), "STF-H3": (15, 0)}
    assert staffing.get("/api/coverage").json() == coverage_before
    assert staffing.get("/api/events", params={"limit": 1}).json()["total"] == events_before
    assert _get(staffing, "assignments")["data_version"] == coverage_before["data_version"]


def test_simulate_rejects_ineligible_offers(staffing):
    body = {"action": {"kind": "split_shift", "physician_id": "STF-P10", "duration_minutes": 120}}
    result = staffing.post(f"{BASE}/simulate", json=body).json()

    assert result["allowed"] is False and result["projections"] == []
    assert [v["code"] for v in result["violations"]] == ["no_overlap"]


# Time, live events, caching ----------------------------------------------------------


def test_no_future_events_leak_into_recommendations(staffing):
    now = _get(staffing, "assignments")
    assert "STF-C1" in {r["consult_id"] for r in now["plan"]["recommendations"]}
    assert "STF-C7" not in json.dumps(now)  # received 21:05Z
    eligible = [c for c in _get(staffing, "split-shifts")["candidates"] if c["eligible"]]
    assert [c["physician_id"] for c in eligible] == ["STF-P7"]  # shift_started 21:20Z unseen

    later = _get(staffing, "assignments", as_of="2031-04-08T21:04:00Z")
    skipped = {s["consult_id"]: s["assigned_physician_id"] for s in later["skipped"]}
    assert skipped["STF-C1"] == "STF-P1"  # the 21:03Z assignment is visible by then


def test_injected_event_changes_recommendations_and_invalidates_cache(staffing):
    first = _get(staffing, "assignments")
    assert _get(staffing, "assignments") == first  # cached, deterministic
    response = staffing.post(
        "/api/events",
        json={
            "event_id": "LIVE-STF-1",
            "event_type": "outgoing_call_started",
            "event_time": "2031-04-08T20:59:50Z",
            "physician_id": "STF-P1",
            "consult_id": "STF-C5",
            "hospital_id": "STF-H1",
        },
    )
    assert response.status_code == 201, response.text
    after = _get(staffing, "assignments")
    recs = {r["consult_id"]: r["physician_id"] for r in after["plan"]["recommendations"]}

    assert after["data_version"] > first["data_version"]
    assert "STF-C1" not in recs and recs["STF-C2"] == "STF-P4"
    c1 = next(u for u in after["plan"]["unassigned"] if u["consult_id"] == "STF-C1")
    assert c1["reason_code"] == "no_eligible_physician"


# Read-only, errors, fallback ---------------------------------------------------------


def test_optimization_endpoints_are_read_only(staffing):
    for path in ("assignments", "split-shifts", "comparison"):
        assert staffing.post(f"{BASE}/{path}").status_code == 405
    assert staffing.get(f"{BASE}/simulate").status_code == 405
    spec = staffing.get("/openapi.json").json()["paths"]
    methods = {p: sorted(ops) for p, ops in spec.items() if p.startswith(BASE)}
    assert methods == {
        f"{BASE}/input": ["get"],
        f"{BASE}/assignments": ["get"],
        f"{BASE}/split-shifts": ["get"],
        f"{BASE}/comparison": ["get"],
        f"{BASE}/simulate": ["post"],
    }


def test_errors_use_the_standard_envelope(client):
    for path in ("assignments", "split-shifts", "comparison"):
        body = client.get(f"{BASE}/{path}").json()
        assert body["error"]["code"] == "no_dataset"
    body = {"action": {"kind": "split_shift", "physician_id": "X"}}
    assert client.post(f"{BASE}/simulate", json=body).json()["error"]["code"] == "no_dataset"
    client.post("/api/datasets/sample", params={"name": "synthetic_staffing"})
    naive = client.get(f"{BASE}/assignments", params={"as_of": "2031-04-08T21:00:00"})
    assert naive.status_code == 422 and naive.json()["error"]["code"] == "validation_error"
    bad = client.post(f"{BASE}/simulate", json={"action": {"kind": "teleport"}})
    assert bad.status_code == 422


def test_labelled_fallback_when_ortools_is_missing(staffing, monkeypatch):
    monkeypatch.setattr(routing_solve, "load_min_cost_flow", lambda: None)
    monkeypatch.setattr(cpsat, "load_cp_model", lambda: None)
    dispatch = _get(staffing, "assignments")
    plan = _get(staffing, "split-shifts")

    assert dispatch["solver"]["status"] == "FALLBACK" and dispatch["solver"]["fallback_used"]
    assert not dispatch["solver"]["proven_optimal"]
    assert dispatch["plan"]["method"] == "fallback_greedy"
    assert {r["consult_id"]: r["physician_id"] for r in dispatch["plan"]["recommendations"]} == {
        "STF-C1": "STF-P1",
        "STF-C2": "STF-P4",
        "STF-C3": "STF-P5",
    }
    assert plan["solver"]["status"] == "FALLBACK" and plan["solver"]["solver"] == "fallback_greedy"
    assert plan["totals"]["deficit_physician_minutes_after"] == 60
    assert all(
        c["eligible"] or c["physician_id"] != plan["recommendations"][0]["physician_id"]
        for c in plan["candidates"]
    )


def test_explicit_error_when_fallback_is_disabled(make_client, tmp_path, monkeypatch):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"solver": {"allow_fallback": False}}))
    monkeypatch.setattr(routing_solve, "load_min_cost_flow", lambda: None)
    with make_client(optimization_policy_file=policy) as client:
        client.post("/api/datasets/sample", params={"name": "synthetic_staffing"})
        response = client.get(f"{BASE}/assignments")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "optimizer_unavailable"


def test_policy_file_changes_results_without_code_changes(make_client, tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"staffing": {"max_new_physicians": 0}}))
    with make_client(optimization_policy_file=policy) as client:
        client.post("/api/datasets/sample", params={"name": "synthetic_staffing"})
        result = client.get(f"{BASE}/split-shifts").json()

    assert result["recommendations"] == []
    assert result["totals"]["deficit_physician_minutes_after"] == 195


# Phase 2/3 outputs are unchanged by Phase 4 ------------------------------------------


def test_phase3_outputs_unchanged_by_optimization_calls(staffing):
    before = {
        p: staffing.get(p).json()
        for p in ("/api/coverage", "/api/alerts", "/api/state", "/api/optimization/input")
    }
    _get(staffing, "assignments")
    _get(staffing, "split-shifts")
    _get(staffing, "comparison")
    staffing.post(
        f"{BASE}/simulate",
        json={"action": {"kind": "split_shift", "physician_id": "STF-P7", "duration_minutes": 240}},
    )
    for path, value in before.items():
        assert staffing.get(path).json() == value, path
    contributors = [c for h in before["/api/coverage"]["hospitals"] for c in h["contributors"]]
    assert all(c["status"] != "proposed" for c in contributors)
