# Sysop tests

Sysop's own upstream tests. **Not installed into consumer repos** — `install.sh` has zero `tests/` references; the test surface lives only in this repo.

## Layout

```
tests/
├── conftest.py                            # env-pop neuter + marker collection-modifier
├── test_smoke.py                          # imports for the load-bearing scripts
├── test_install_*.py                      # integration — drive the real install.sh (concat merge, stack detection, adopt guard, model-role resolution)
├── test_*_sh.py                           # integration — lifecycle shell scripts via subprocess against scratch git repos (Phase 84)
├── test_run_checks*.py                    # the run_checks/ package — stages, YAML config, baseline, crown-jewel coverage gate
├── test_next_task.py                      # ported from gdp (Phase 47c) + unblocker-first ordering (Phase 74)
├── test_validate_tasks.py                 # ported from gdp + Sysop originals (Phase 47c)
├── test_model_roles.py · test_resolve_skill_models.py · test_check_skill_models.py · test_migrate_skill_model.py
│                                          # model-pin guard + role→model resolution (Phases 65b/69)
├── test_pr_dependabot.py                  # Dependabot sweep classifier (Phase 53)
├── test_parse_subagent_envelope.py        # Sysop-original Phase 37 hook (Phase 48)
├── test_permission_denied_hook.py         # Sysop-original Phase 36 hook (Phase 48)
├── test_backfill_completed_dates.py · test_review_index.py · test_archive_review_tasks.py · test_sitrep_survey.py
│                                          # Sysop-original helper suites (Phases 48/82)
├── test_auto_claim_miner.py               # research miners (dev-repo only — excluded from the public mirror)
└── PORT_LOG.md                            # per-test (a)/(b)/(c) classification ledger + originals
```

(The globbed rows cover several files each; `ls tests/` is the authoritative list.)

## Running

```bash
# One-shot
python3 -m pytest

# Faster local iteration — only collect / show structure
python3 -m pytest --collect-only -q

# Skip integration tests that need npx/pip-audit (default on a clean dev box)
python3 -m pytest -m "not requires_node and not requires_pip_audit"
```

## Markers

- `requires_node` — test invokes `npx eslint` (or expects it on PATH). Auto-skips when `npx` is not on PATH (see `conftest.py:pytest_collection_modifyitems`).
- `requires_pip_audit` — same shape, for the `pip-audit` binary.

CI runs without Node or `pip-audit` installed, so all marked tests auto-skip there. The mocked-output coverage in the same file exercises the same parsing surface without the binaries.

## gdp baseline

Before any port, gdp's three matching test files (`test_next_task.py` 41fn, `test_validate_tasks.py` 8fn, `test_run_checks.py` 21fn post-`2fdca506`) were verified passing in the gdp tree on 2026-05-27 via `cd ~/Projects/gdp-query-system && .venv/bin/python3 -m pytest tests/test_next_task.py tests/test_validate_tasks.py tests/test_run_checks.py -v`. Result: **70 passed, 0 skipped, 0 xfail**. All gdp tests in scope were green candidates for porting.

## Branch protection — enforced

`main` requires the `pytest` status check, with `enforce_admins` on — enforced since 2026-06-24. Direct pushes are rejected; changes land via branch → PR → squash-merge (the `pr` merge policy `/review-close` grew in Phase 63 for exactly this shape). Historical note: protection was initially saved-but-unenforced (free-plan private repos don't enforce rules), which is why the suite's early phases relied on the human reading PRs as the gate.

## Why these don't ship downstream

The test surface here exercises Sysop's own helpers as they live in this repo (`core/companion/scripts/`, `scripts/`). A consumer's `install.sh --update` copies the helpers into the consumer's repo, but the consumer doesn't run our test suite — they run their own. Shipping `tests/` into every consumer would (1) double the installer surface, (2) make consumers responsible for `pytest`, and (3) conflate "test Sysop upstream" with "test the installed copy." Tests for the consumer's adaptations of these helpers — if any — are a separate concern that belongs in the consumer's repo.
