# SYNTHETIC SAMPLE DATA — surge & coverage-shortfall scenario

**Everything here is invented.** Scripted to exercise Phase 3: a demand spike, shift ends producing a projected gap, a hospital with no credentialed physician on shift, a missing baseline, and events ingested after the reference time.

Regenerate: `cd backend && .venv/bin/python -m scripts.generate_surge_dataset`

Load: `POST /api/datasets/sample?name=synthetic_surge` or the UI sample picker.

Hand-computed expectations: `backend/tests/test_surge_scenario.py`.
