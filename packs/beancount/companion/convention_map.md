# Convention Map — Beancount pack

> Maps file patterns to conventions for projects that ingest external financial
> data into Beancount ledgers (personal-finance, small-business bookkeeping,
> any "raw vendor dump → normalized double-entry" pipeline).
> Use during planning (before writing code) and review (before committing).

> **Directory placeholders** referenced in this pack: `<vendor data dir>` (the
> repo's top-level directory for raw downloads from external sources — usually
> `data/`; gitignored), `<parsers dir>` (the directory housing per-vendor
> normalizers — typically `parsers/`).
>
> This pack overlays the python pack — Python conventions for `<parsers dir>/*.py`
> still apply (logger formatting, intentional exceptions vs. broad except,
> module-scope regex compilation, etc.). The sections below add patterns
> specific to the vendor-ingest shape.

---

## `<vendor data dir>/**` — Raw vendor downloads (PII)

- **Never commit anything under `<vendor data dir>/`**: Raw CSVs / JSON / PDFs contain account numbers, merchant detail, transaction amounts, and other PII. The repo's `.gitignore` excludes `/<vendor data dir>/` (typically `/data/`). Any committed file under `<vendor data dir>/` is a PII incident — reviewer must reject on sight regardless of how innocuous the content looks.
- **No code reads from `<vendor data dir>/` at import time**: Modules may reference `<vendor data dir>/<inbox subdir>/` as a directory constant but must not enumerate, read, or log its contents at import time. Reads happen inside request / CLI / job handlers only.
- **Carve-out for per-vendor README** (see next section): the `.gitignore` rule may be paired with `!/<vendor data dir>/<vendor>/README.md` entries to allow per-vendor intake documentation — that's the *only* sanctioned exception.

## `<vendor data dir>/<vendor>/README.md` — Per-vendor intake README

- **Allowed to commit**: a single `README.md` under each `<vendor data dir>/<vendor>/` subtree documents that vendor's dump shape (folder layout, file naming, dated-subdir convention, schema-drift recovery procedure, locality notes). This is the natural home for that documentation — adjacent to the data it describes — and is the ONLY file under `<vendor data dir>/` that is sanctioned for commit.
- **Synthetic content only**: NO real account numbers, payees, amounts, addresses, or other PII. All examples use obvious placeholders (e.g., `<vendor data dir>/Acme/<request-date>/`, account number `000-0000000-0000001`, address `123 SYNTHETIC ST`). Treat any digit string that *looks* like a real account or transaction ID as a PII incident, even if it's fabricated — the visual signal is what matters to a reviewer scanning at speed.
- **`.gitignore` carve-out required**: each per-vendor README needs its own `!/<vendor data dir>/<vendor>/README.md` line in `.gitignore` (the recursive `<vendor data dir>/` rule defaults to ignoring everything). Add the carve-out in the same commit that introduces the README.
- **Cross-reference the parser**: the README should name the parser module(s) that consume this vendor's data and the schema-baseline hash file (if any) gating it. Reviewers checking the README in isolation should be able to find the consuming code from the README alone.

## `<parsers dir>/*.py` — Vendor-data parsers (overlay on python pack)

- **`base_dir` containment**: every parser entry point accepts a `base_dir=` argument and uses `os.path.realpath()` to reject paths escaping it. Callers always pass the configured `<vendor data dir>/<inbox subdir>/` so a parser can't read outside the intake tree.
- **Explicit text encoding**: every `open()` / `Path.read_text()` / `Path.write_text()` call passes `encoding="utf-8"` explicitly. Vendor dumps often arrive in mixed encodings; relying on the platform default produces silent garbling on macOS / Windows.
- **No mutation of source files**: parsers READ from `<vendor data dir>/` and WRITE elsewhere (typically a normalized Beancount fragment or a queue file). Never `os.rename`, `os.remove`, or otherwise mutate the raw vendor file — the raw is forensic evidence if the parse is wrong.
- **Idempotent against re-ingest**: parsing the same vendor file twice produces the same output (no timestamps in payload, deterministic row ordering, stable transaction IDs derived from row content). This is what lets a re-ingest after a parser-bug fix recover cleanly.

## `<parsers dir>/*.sha256` — External-schema baseline hashes

- **Single-line hex**: contents are exactly one 64-char (SHA-256) lowercase hex string followed by a single newline. No other content; no trailing whitespace; no commentary on the same line.
- **Generation reproducible**: the consuming parser's module docstring documents the exact command used to regenerate the hash from the corresponding source file, e.g., `shasum -a 256 < path/to/source.csv | awk '{print $1}'`. Anyone bumping the file should be able to copy-paste that command without further guessing.
- **Update path is hand-edit only**: when the source file changes (vendor schema drift), the parser refuses with an 8-hex-prefix mismatch error and the parser docs / vendor README direct the user to bump this file. Never auto-update from inside the parser — the bump is a deliberate gate that forces the human to compare old vs. new vendor shape and update column-handling code accordingly.
- **One baseline per drift-gated source**: each schema-baseline file pairs 1:1 with a vendor-controlled source file (e.g., `<parsers dir>/acme_file_descriptions.sha256` ↔ `<vendor data dir>/Acme/<dated>/acme_FileDescriptions.csv`). The pairing is documented in the consuming parser; reviewers should be able to find the source-file path from the parser without grepping.

## `<ledger>.beancount` — Top-level Beancount ledger

- **No PII in `git`-tracked ledgers**: any committed Beancount file uses synthetic accounts, payees, and amounts only — same standard as test fixtures. Real ledgers live outside the repo (or in a gitignored `<vendor data dir>/private-ledger/` subdir) and are referenced via `include` directives in a local-only top-level file.
- **Account hierarchy stability**: account names (`Assets:Bank:Checking`, `Income:Salary:Employer`) are stable IDs — renames require a one-shot rewrite pass across all transactions, not partial edits. Parsers emit accounts using the project's canonical hierarchy; new accounts get added to the hierarchy before transactions reference them.
- **`bean-check` passes on every commit**: the project's pre-commit hook (or equivalent) runs `bean-check <ledger>.beancount` against the canonical top-level ledger and refuses commits that fail. Parser changes that produce malformed Beancount syntax fail this gate.
