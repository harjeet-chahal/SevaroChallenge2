# SYNTHETIC SAMPLE DATA — dispatch & split-shift staffing scenario

**Everything here is invented.** Scripted to exercise Phase 4: a stroke consult that least-loaded routing strands, a ringing call, a consult with no eligible physician, and a projected gap that exactly one off-shift physician can cover while six others each fail one split-shift rule. The eligible physician is also credentialed at a busy hospital without a gap (the split-shift trap).

Regenerate: `cd backend && .venv/bin/python -m scripts.generate_staffing_dataset`

Load: `POST /api/datasets/sample?name=synthetic_staffing` or the UI sample picker.

Hand-computed expectations: `backend/tests/test_optimization_scenario.py`.
