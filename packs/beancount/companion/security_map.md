# Security Concern Map — Beancount pack

> Maps file patterns to OWASP security checks for vendor-ingest pipelines that
> normalize external financial data into Beancount ledgers.
> Used by `/security-audit` to focus agents on applicable checks per file area.
> Each section lists what TO check and what to SKIP.

> Overlays the python pack — Python-side OWASP checks for `<parsers dir>/*.py`
> still apply (log sanitization, intentional exception types, input validation).
> Sections below add the vendor-ingest-specific concerns.

---

## `<vendor data dir>/**` — Raw vendor downloads (PII)

**Check:**
- **A02 Data Exposure**: nothing under `<vendor data dir>/` may be committed except the per-vendor README (next section). The recursive `.gitignore` rule (`/<vendor data dir>/`) is the load-bearing control; any commit that adds a tracked file under this tree is a PII incident regardless of file size or apparent content. `/security-audit` MUST grep `git ls-files <vendor data dir>/` and flag any output that is not a `README.md` under a direct vendor subdir.
- **A04 Insecure Design**: import-time enumeration of `<vendor data dir>/` is forbidden — a module that lists / opens / hashes vendor files at import time leaks structural metadata into logs and may surface PII in stack traces. Reads happen inside request / CLI / job handlers only, after explicit user / scheduler invocation.

**Skip:** Everything else — the dir is data-at-rest, not code; OWASP categories don't apply.

---

## `<vendor data dir>/<vendor>/README.md` — Per-vendor intake README

**Check:**
- **A02 Data Exposure**: contents must be synthetic — placeholder account numbers (`000-0000000-0000001`), placeholder payees (`GENERIC COFFEE SHOP`), placeholder addresses (`123 SYNTHETIC ST`). Any digit string that *looks* like a real account or transaction ID is a PII incident, even if fabricated — the visual signal triggers reviewer suspicion regardless of provenance.
- **A05 Misconfiguration**: the README's existence depends on a paired `.gitignore` carve-out (`!/<vendor data dir>/<vendor>/README.md`). If `git ls-files` shows the README but `.gitignore` lacks the carve-out, someone bypassed the ignore rule and the file's tracked status is fragile to a future `.gitignore` cleanup.

**Skip:** A01, A03, A06, A07, A08, A10 (file is plain Markdown, no code execution, no auth, no external requests).

---

## `<parsers dir>/*.py` — Vendor-data parsers (overlay)

**Check:**
- **A01 Access Control**: `base_dir` containment — every entry point that takes a path argument resolves it through `os.path.realpath()` against the configured `<vendor data dir>/<inbox subdir>/` and rejects paths whose real-path escapes the base. Without this check, a maliciously-named symlink (or a user-supplied path in a CLI invocation) reads from anywhere on disk.
- **A03 Injection**: CSV / JSON / PDF parsers run on attacker-influenced content (the vendor controls the dump format; a compromised vendor or MITM'd download can inject crafted payloads). Use defusedxml for any XML input; never `eval` / `exec` parsed content; bound numeric conversions (`Decimal`, not `float`) with explicit precision.
- **A04 Insecure Design**: parsers MUST NOT mutate source files (`os.rename` / `os.remove` / overwrite the raw vendor dump). Raw is forensic evidence. Parsers READ from `<vendor data dir>/` and WRITE elsewhere.
- **A05 Misconfiguration**: explicit `encoding="utf-8"` on every file-IO call (vendor encodings vary; platform-default decoding is non-deterministic across macOS / Linux / Windows). Decimal precision configured explicitly (no implicit float rounding on currency amounts).
- **Logging**: never log raw transaction details (payee, amount, account number) at INFO or above — those propagate to log aggregators. DEBUG-level logging of structural metadata (file path, row count, parse duration) is fine. If a parse error references a row, log the row's content-derived hash, not the row content itself.

**Skip:** A06 (dependencies — covered upstream), A07 (no auth in parsers), A10 (parsers read local files, no outbound HTTP).

---

## `<parsers dir>/*.sha256` — External-schema baseline hashes

**Check:**
- **A02 Data Exposure**: file contains a SHA-256 of vendor-documented column shape, NOT user data. The hash itself is safe to include in error messages (8-char prefix for `grep`-ability) and safe to commit. Verify no per-user / per-account data leaked into the hashed source before the baseline was generated — the baseline should hash a column-descriptor file or schema file, never an actual data row.
- **A05 Misconfiguration**: any bump to a baseline must be a deliberate hand-edit gated on a human comparing the old vs new vendor file. The parser MUST NOT auto-update its own baseline — that defeats the drift-gate. `/security-audit` flags any code path inside `<parsers dir>/` that writes to `*.sha256`.
- **A08 Integrity**: the baseline pairs 1:1 with a source file; the pairing is documented in the consuming parser. A baseline with no documented source-file pairing (or a parser referencing a baseline that doesn't exist on disk) is a broken integrity check — flag it.

**Skip:** Everything else — file is content-derived, deterministic, and tiny.

---

## `<ledger>.beancount` — Top-level Beancount ledger

**Check:**
- **A02 Data Exposure**: committed Beancount content uses synthetic accounts, payees, and amounts only — same standard as test fixtures. Real ledger data lives outside the repo or in a gitignored `<vendor data dir>/private-ledger/` subdir and is referenced via `include` directives in a local-only top-level file (which is itself gitignored).
- **A05 Misconfiguration**: the project's pre-commit hook (or equivalent) runs `bean-check` against the canonical top-level ledger and refuses malformed-syntax commits. Parser changes that produce invalid Beancount fail this gate before they land. Confirm the hook exists and is armed (`.git/hooks/pre-commit` references `bean-check`).
- **A08 Integrity**: account-name renames are one-shot rewrites across all transactions, not partial edits. A diff that renames `Assets:Bank:Old` → `Assets:Bank:New` in some transactions but not others is a data-integrity break — `bean-check` may pass while reports double-count. Flag any rename diff that leaves both names referenced.

**Skip:** A01, A03, A07, A10 (file is plain-text accounting data, no auth, no execution, no I/O).
