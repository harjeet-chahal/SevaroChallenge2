# SYNTHETIC SAMPLE DATA — surge scenario + split-shift workflow demo

**Everything here is invented.** The surge scenario (`synthetic_surge`) plus a backup split-shift candidate (Dr. Yara Surge, SRG-P8) and a busy hospital without a gap (Lakeshore, SRG-H4) where the recommended physician is also credentialed. Built for the Phase 5 demo: propose → approve → offer → accept → activate, conflicting acceptances and split-shift trap protection.

Regenerate: `cd backend && .venv/bin/python -m scripts.generate_workflow_dataset`

Load: `POST /api/datasets/sample?name=synthetic_workflow` or the UI sample picker.

Expectations: `backend/tests/test_workflow.py`.
