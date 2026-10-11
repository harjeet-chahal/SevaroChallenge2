"""Voluntary availability: off-shift portal → persistence → ranking → proposal → cost.

Engine scenarios use the hand-solvable base from test_optimization_staffing: H1 needs one
physician all day and its only physician leaves at +60, so the planning window (240 min)
has 180 deficit physician-minutes from +60.

HTTP scenarios use the workflow sample (18:35 EDT): Ridge has a gap now; Dr. Vale Surge
(online in 20 min) removes 220 physician-minutes and Dr. Yara Surge (35 min) 205.
"""

from __future__ import annotations

from datetime import timedelta

from opt_helpers import NOW, OptScenario, analyze, config, m
from workflow_helpers import (
    COORD,
    LEAD,
    REF,
    RIDGE,
    RIDGE_GAP_ALERT,
    VALE,
    YARA,
    advance,
    decide,
    doctor,
    intervention,
    load,
    propose_ok,
    respond,
    send,
)

from app.engines.optimization import OptimizationConfig, run_staffing
from app.engines.optimization.split_shift import AvailabilityWindow

WREN = "SRG-P7"  # credentialed at Ridge, not opted in
ON_SHIFT = "SRG-P1"
EDT = "-04:00"


def at(clock: str, day: int = 10) -> str:
    """Workflow-sample local time (EDT) as an ISO timestamp."""
    return f"2030-09-{day:02d}T{clock}:00{EDT}"


def share(client, pid: str, start: str, end: str):
    return client.post(
        "/api/availability", headers=doctor(pid), json={"start_at": start, "end_at": end}
    )


def share_ok(client, pid: str, start: str, end: str) -> dict:
    response = share(client, pid, start, end)
    assert response.status_code == 201, response.text
    return response.json()


def staffing(client) -> dict:
    response = client.get("/api/optimization/split-shifts")
    assert response.status_code == 200, response.text
    return response.json()


def ridge(client) -> list[dict]:
    result = staffing(client)
    (ranking,) = [r for r in result["rankings"] if r["hospital_ids"] == [RIDGE]]
    return ranking["entries"]


def ranked(entries: list[dict]) -> list[str]:
    return [e["physician_id"] for e in entries if e["rank"] is not None]


def workflow_version(client) -> int:
    return client.get("/api/config").json()["workflow_version"]


# --------------------------------------------------------------------- engine --


def base() -> OptScenario:
    s = OptScenario().hospital("H1").requirement("H1", "00:00", "00:00", 1)
    return s.doctor("P1", ["H1"], end=m(60))


def window(pid: str, start: float, end: float) -> dict[str, list[AvailabilityWindow]]:
    return {pid: [AvailabilityWindow(f"AV-{pid}", pid, m(start), m(end))]}


def two_candidates(rested_at: float) -> OptScenario:
    """G can cover the whole gap; K is rested only at ``rested_at`` minutes from now."""
    return base().candidate("G", ["H1"]).candidate("K", ["H1"], last_end=m(rested_at - 10 * 60))


def run(s: OptScenario, availability=None, cfg: OptimizationConfig | None = None):
    return run_staffing(analyze(s), cfg or OptimizationConfig(), availability=availability)


def test_without_volunteers_the_result_is_unchanged():
    s = two_candidates(70)

    def stable(r):
        return r.model_dump(exclude={"solver": {"wall_time_ms", "stages"}})

    plain, _ = run(s)
    empty, _ = run(s, availability={})
    assert stable(plain) == stable(empty)
    assert [r.physician_id for r in plain.recommendations] == ["G"]
    assert plain.voluntary is not None and plain.voluntary.applied is False
    assert [st["name"] for st in plain.solver.stages][0] == "deficit"
    assert not any(st["name"].startswith("voluntary") for st in plain.solver.stages)


def test_volunteer_within_tolerance_replaces_the_reference_choice():
    # K covers [+70, +240) = 170 of the 180 G covers (94% >= 85%), inside the window.
    s = two_candidates(70)
    result, _ = run(s, availability=window("K", 0, 300))

    assert [r.physician_id for r in result.recommendations] == ["K"]
    (rec,) = result.recommendations
    assert rec.voluntary is not None and rec.voluntary.status == "applied"
    assert rec.voluntary.offer_within_window
    assert result.totals.physicians_used == 1  # replaced, never added
    assert result.totals.deficit_physician_minutes_after == 10
    assert result.voluntary.applied and result.voluntary.reference_physicians == ["Dr G"]
    assert any(st["name"] == "voluntary" for st in result.solver.stages)

    (ranking,) = result.rankings
    first, second = ranking.entries[:2]
    assert (first.physician_id, first.rank, first.rank_without_voluntary) == ("K", 1, 2)
    assert first.movement == 1 and first.voluntary_preference_applied
    assert any("Moved up from #2 to #1" in r for r in first.reasons)
    assert (second.physician_id, second.movement) == ("G", -1)


def test_volunteer_outside_tolerance_is_not_preferred_and_not_added():
    # K is rested only at +120: 120 of 180 (67% < 85%): G stays, K is not added on top.
    s = two_candidates(120)
    result, _ = run(s, availability=window("K", 0, 300))

    assert [r.physician_id for r in result.recommendations] == ["G"]
    assert result.totals.physicians_used == 1
    assert result.voluntary.applied is False
    entries = {e.physician_id: e for e in result.rankings[0].entries}
    assert entries["G"].rank == 1 and entries["K"].rank == 2
    assert entries["K"].voluntary.status == "outside_tolerance"
    assert entries["K"].movement == 0


def test_zero_tolerance_only_breaks_exact_ties():
    cfg = config(voluntary={"coverage_tolerance": 0.0})
    s = two_candidates(70)
    result, _ = run(s, availability=window("K", 0, 300), cfg=cfg)
    assert [r.physician_id for r in result.recommendations] == ["G"]

    # Equal coverage (both rested now): the volunteer wins the tie.
    tie = base().candidate("G", ["H1"]).candidate("K", ["H1"])
    result, _ = run(tie, availability=window("K", 0, 300), cfg=cfg)
    assert [r.physician_id for r in result.recommendations] == ["K"]


def test_policy_switch_turns_the_preference_off():
    cfg = config(voluntary={"enabled": False})
    result, _ = run(two_candidates(70), availability=window("K", 0, 300), cfg=cfg)
    assert [r.physician_id for r in result.recommendations] == ["G"]
    k = next(c for c in result.candidates if c.physician_id == "K")
    assert k.voluntary is not None and k.voluntary.status == "disabled"


def test_window_that_cannot_hold_a_valid_offer_is_not_used():
    # 90 minutes is shorter than the 2-hour minimum offer.
    result, _ = run(two_candidates(70), availability=window("K", 50, 140))
    assert [r.physician_id for r in result.recommendations] == ["G"]
    k = next(e for e in result.rankings[0].entries if e.physician_id == "K")
    assert k.voluntary.status == "no_offer_fits" and k.voluntary.overlaps_shortage


def test_window_outside_the_shortage_does_not_count():
    s = two_candidates(70)
    result, _ = run(s, availability=window("K", 300, 600))
    assert [r.physician_id for r in result.recommendations] == ["G"]
    k = next(c for c in result.candidates if c.physician_id == "K")
    assert k.voluntary.status == "no_shortage_overlap" and k.voluntary.overlap_minutes == 0


def test_ineligible_volunteer_is_listed_but_never_ranked():
    s = base().candidate("G", ["H1"]).candidate("X", ["H1"], opt_in=False)
    result, _ = run(s, availability=window("X", 0, 300))
    assert [r.physician_id for r in result.recommendations] == ["G"]
    x = next(e for e in result.rankings[0].entries if e.physician_id == "X")
    assert x.rank is None and x.eligible is False
    assert x.voluntary.status == "not_eligible"


def test_overlap_minutes_and_shortage_bounds():
    result, _ = run(two_candidates(70), availability=window("K", 100, 400))
    k = next(c for c in result.candidates if c.physician_id == "K")
    # Shortage runs from +60 to the end of the 240-min window; [+100, +240) is inside.
    assert k.voluntary.overlap_minutes == 140
    assert k.voluntary.shortage_start == m(100) and k.voluntary.shortage_end == m(240)


def test_cost_uses_one_rate_for_everyone():
    result, _ = run(two_candidates(70), availability=window("K", 0, 300))
    entries = {e.physician_id: e for e in result.rankings[0].entries}
    rate = OptimizationConfig().cost.hourly_rate
    for e in entries.values():
        assert e.cost.hourly_rate == rate
        assert e.cost.amount == round(e.cost.paid_minutes / 60 * rate, 2)
        assert e.cost.basis == "simulated"
    assert result.cost is not None and result.cost.recommended.basis == "simulated"
    labels = [c.label for c in result.cost.comparisons]
    assert "Plan without voluntary availability" in labels
    assert all(c.basis == "simulated" for c in result.cost.comparisons)


def test_window_options_start_and_end_inside_the_window():
    s = two_candidates(70)
    _, internals = run(s, availability=window("K", 30, 280))
    inside = [
        o
        for o in internals.options
        if o.physician_id == "K" and internals.ctx.window_for("K", o.start, o.end)
    ]
    assert inside and all(m(30) <= o.start and o.end <= m(280) for o in inside)
    assert NOW + timedelta(minutes=70) <= min(o.start for o in inside)


# ----------------------------------------------------------------------- HTTP --


def test_submission_is_persisted_audited_and_not_an_assignment(client):
    load(client)
    before = workflow_version(client)
    created = share_ok(client, YARA, at("18:35"), at("22:35"))

    assert created["status"] == "active" and created["phase"] == "current"
    assert created["duration_minutes"] == 240 and created["timezone"] == "America/Chicago"
    assert created["can_update"] and created["can_withdraw"]
    assert "not a shift assignment" in created["message"]
    assert workflow_version(client) > before  # live refresh signal

    mine = client.get("/api/availability/mine", headers=doctor(YARA)).json()
    assert [i["id"] for i in mine["items"]] == [created["id"]]
    assert mine["min_useful_window_minutes"] == 120 + 35
    staff = client.get("/api/availability", headers=COORD).json()
    assert [i["physician_id"] for i in staff["items"]] == [YARA]
    assert not staff["items"][0]["can_update"]  # staff read, never edit

    audit = client.get("/api/audit", headers=COORD).json()["items"]
    assert audit[0]["action"] == "availability_submitted"
    assert audit[0]["entity_id"] == created["id"]

    # Nothing was offered or proposed.
    assert client.get("/api/offers/mine", headers=doctor(YARA)).json() == []
    assert client.get("/api/interventions", headers=COORD).json()["total"] == 0


def test_validation_and_permissions(client):
    load(client)
    assert share(client, YARA, at("20:00"), at("19:00")).status_code == 422
    assert share(client, YARA, at("18:00"), at("18:30")).status_code == 422  # already over
    assert share(client, YARA, at("18:00"), at("21:00")).status_code == 422  # starts in the past
    assert share(client, YARA, at("19:00"), at("19:20")).status_code == 422  # too short
    assert share(client, ON_SHIFT, at("19:00"), at("23:00")).status_code == 422
    body = {"start_at": at("19:00"), "end_at": at("23:00")}
    assert client.post("/api/availability", headers=COORD, json=body).status_code == 403
    no_id = {"X-Demo-Role": "physician"}
    assert client.post("/api/availability", headers=no_id, json=body).status_code == 401
    naive = {"start_at": "2030-09-10T19:00:00", "end_at": "2030-09-10T23:00:00"}
    assert client.post("/api/availability", headers=doctor(YARA), json=naive).status_code == 422

    first = share_ok(client, YARA, at("19:00"), at("23:00"))
    clash = share(client, YARA, at("22:00"), at("23:30"))
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "availability_overlap"
    assert share(client, VALE, at("19:00"), at("23:00")).status_code == 201  # others unaffected

    other = client.post(f"/api/availability/{first['id']}/withdraw", headers=doctor(VALE))
    assert other.status_code == 403
    assert client.get("/api/availability/AV-9999", headers=COORD).status_code == 404
    assert client.get("/api/availability", headers=doctor(YARA)).status_code == 403


def test_volunteer_moves_up_in_the_ranking(client):
    load(client)
    before = ridge(client)
    assert ranked(before) == [VALE, YARA]
    assert all(e["voluntary"] is None for e in before)

    share_ok(client, YARA, at("18:35"), at("22:35"))
    after = ridge(client)
    assert ranked(after) == [YARA, VALE]
    yara, vale = after[0], after[1]
    assert (yara["rank"], yara["rank_without_voluntary"], yara["movement"]) == (1, 2, 1)
    assert yara["voluntary_preference_applied"] and yara["in_plan"]
    assert yara["voluntary"]["status"] == "applied" and yara["voluntary"]["overlaps_shortage"]
    assert yara["reasons"][0].startswith("Moved up from #2 to #1")
    assert (vale["rank"], vale["movement"]) == (2, -1)
    assert yara["cost"]["amount"] == vale["cost"]["amount"]  # volunteering is not cheaper

    result = staffing(client)
    assert result["recommendations"][0]["physician_id"] == YARA
    assert result["voluntary"]["applied"] is True
    assert result["voluntary"]["reference_physicians"] == ["Dr. Vale Surge"]
    yara_row = next(c for c in result["candidates"] if c["physician_id"] == YARA)
    assert yara_row["voluntary"]["status"] == "applied"


def test_ineligible_volunteer_does_not_change_the_plan(client):
    load(client)
    share_ok(client, WREN, at("18:35"), at("22:35"))
    entries = ridge(client)
    assert ranked(entries) == [VALE, YARA]
    wren = next(e for e in entries if e["physician_id"] == WREN)
    assert wren["rank"] is None and wren["voluntary"]["status"] == "not_eligible"
    notes = client.get("/api/availability/mine", headers=doctor(WREN)).json()["notes"]
    assert any("not opted in" in n for n in notes)


def test_window_outside_the_shortage_or_too_short_is_not_preferred(client):
    load(client)
    late = share_ok(client, YARA, at("08:00", day=11), at("12:00", day=11))
    entries = ridge(client)
    assert ranked(entries) == [VALE, YARA]
    yara = next(e for e in entries if e["physician_id"] == YARA)
    assert yara["voluntary"]["status"] == "no_shortage_overlap"

    client.post(f"/api/availability/{late['id']}/withdraw", headers=doctor(YARA))
    share_ok(client, YARA, at("18:35"), at("20:05"))  # 90 min < 2 h + 35 min to come online
    yara = next(e for e in ridge(client) if e["physician_id"] == YARA)
    assert yara["rank"] == 2 and yara["voluntary"]["status"] == "no_offer_fits"


def test_withdrawal_removes_the_preference_immediately(client):
    load(client)
    created = share_ok(client, YARA, at("18:35"), at("22:35"))
    assert ranked(ridge(client)) == [YARA, VALE]
    version = workflow_version(client)

    response = client.post(f"/api/availability/{created['id']}/withdraw", headers=doctor(YARA))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "withdrawn" and body["phase"] == "withdrawn"
    assert not body["can_update"] and workflow_version(client) > version

    entries = ridge(client)
    assert ranked(entries) == [VALE, YARA]
    assert all(e["voluntary"] is None and e["movement"] == 0 for e in entries)
    assert staffing(client)["voluntary"]["applied"] is False
    assert client.get("/api/availability", headers=COORD).json()["total"] == 0
    history = client.get("/api/availability", headers=COORD, params={"scope": "all"}).json()
    assert [i["status"] for i in history["items"]] == ["withdrawn"]

    again = client.post(f"/api/availability/{created['id']}/withdraw", headers=doctor(YARA))
    assert again.status_code == 200 and again.json()["version"] == body["version"]
    update = client.put(
        f"/api/availability/{created['id']}",
        headers=doctor(YARA),
        json={"start_at": at("19:00"), "end_at": at("23:00")},
    )
    assert update.status_code == 409


def test_update_moves_the_window_and_reranks(client):
    load(client)
    created = share_ok(client, YARA, at("18:35"), at("22:35"))
    url = f"/api/availability/{created['id']}"
    moved = client.put(
        url,
        headers=doctor(YARA),
        json={"start_at": at("08:00", 11), "end_at": at("12:00", 11), "expected_version": 1},
    )
    assert moved.status_code == 200 and moved.json()["version"] == 2
    assert ranked(ridge(client)) == [VALE, YARA]

    stale = client.put(
        url,
        headers=doctor(YARA),
        json={"start_at": at("18:35"), "end_at": at("22:35"), "expected_version": 1},
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_version"
    back = client.put(
        url, headers=doctor(YARA), json={"start_at": at("18:35"), "end_at": at("22:35")}
    )
    assert back.status_code == 200
    assert ranked(ridge(client)) == [YARA, VALE]
    actions = [a["action"] for a in client.get("/api/audit", headers=COORD).json()["items"]]
    assert actions.count("availability_updated") == 2


def test_current_window_can_extend_its_end_after_it_started(client):
    load(client)
    created = share_ok(client, YARA, at("18:35"), at("21:00"))
    advance(client, 10)
    response = client.put(
        f"/api/availability/{created['id']}",
        headers=doctor(YARA),
        json={"start_at": created["start_at"], "end_at": at("22:45")},
    )
    assert response.status_code == 200, response.text


def test_proposal_defaults_to_the_volunteer_with_ranking_and_cost(client):
    load(client)
    share_ok(client, YARA, at("18:35"), at("22:35"))
    preview = client.post(
        "/api/interventions/preview",
        headers=COORD,
        json={"type": "split_shift", "alert_id": RIDGE_GAP_ALERT},
    ).json()
    assert preview["valid"], preview["blocking_reasons"]
    draft = preview["intervention"]
    primary = draft["offer_plan"][0]
    assert primary["physician_id"] == YARA
    assert primary["voluntary"]["status"] == "applied" and primary["cost"]["amount"] == 800

    rec = draft["recommendation"]
    assert [e["physician_id"] for e in rec["ranking"]["entries"] if e["rank"]] == [YARA, VALE]
    assert rec["why"][0].startswith("Ranked #1 of 2 eligible for this need (#2 without")
    cost = rec["cost"]
    assert cost["recommended"]["basis"] == "simulated"
    vale = next(c for c in cost["comparisons"] if "Vale" in c["label"])
    assert "first choice without voluntary availability" in vale["label"]
    assert vale["saving"] == 0 and vale["basis"] == "simulated"
    manual = next(c for c in cost["comparisons"] if c["label"].startswith("Manual"))
    assert manual["saving"] == 400  # 6 h vs 4 h at the same rate
    assert draft["confirmed_cost"] is None


def test_coordinator_can_still_choose_another_physician(client):
    load(client)
    share_ok(client, YARA, at("18:35"), at("22:35"))
    created = propose_ok(client, physician_ids=[VALE, YARA])
    assert [p["physician_id"] for p in created["offer_plan"]] == [VALE, YARA]
    assert created["offer_plan"][1]["voluntary"]["status"] == "applied"


def test_withdrawn_availability_is_reported_at_approval(client):
    load(client)
    created = share_ok(client, YARA, at("18:35"), at("22:35"))
    proposal = propose_ok(client)
    assert proposal["offer_plan"][0]["physician_id"] == YARA
    client.post(f"/api/availability/{created['id']}/withdraw", headers=doctor(YARA))

    response = decide(client, proposal["id"])
    assert response.status_code == 200, response.text  # a preference never blocks approval
    lines = response.json()["approval"]["revalidation"]
    assert any("no longer voluntarily available" in line for line in lines)


def test_full_flow_offer_reason_and_confirmed_cost(client):
    load(client)
    share_ok(client, YARA, at("18:35"), at("22:35"))
    proposal = propose_ok(client)
    assert decide(client, proposal["id"], headers=LEAD).status_code == 200
    sent = send(client, proposal["id"]).json()
    (offer,) = sent["offers"]
    assert offer["physician_id"] == YARA
    view = client.get("/api/offers/mine", headers=doctor(YARA)).json()[0]
    assert "availability you shared" in view["reason"]

    assert respond(client, offer["id"], YARA).status_code == 200
    advance(client, 241)
    done = intervention(client, proposal["id"])
    assert done["status"] == "completed"
    confirmed = done["confirmed_cost"]
    assert confirmed["basis"] == "confirmed" and confirmed["amount"] == 800
    assert done["confirmed_savings"] and all(
        s["basis"] == "confirmed" for s in done["confirmed_savings"]
    )
    # The proposal's projection stays labelled simulated.
    assert done["recommendation"]["cost"]["recommended"]["basis"] == "simulated"


def test_availability_belongs_to_the_loaded_dataset(client):
    load(client)
    share_ok(client, YARA, at("18:35"), at("22:35"))
    load(client)  # a full re-import starts a new day
    assert client.get("/api/availability/mine", headers=doctor(YARA)).json()["items"] == []
    assert ranked(ridge(client)) == [VALE, YARA]
    assert REF.startswith("2030-09-10T22:35")
