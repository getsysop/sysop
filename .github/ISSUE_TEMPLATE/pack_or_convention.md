---
name: Pack or convention proposal
about: Propose a new pack, or conventions to add to an existing one
title: ''
labels: enhancement
assignees: ''
---

**Stack / pack**
Which language, framework, or tool? (e.g. an existing placeholder pack like `flutter`, or a new one.)

**Where these come from**
Conventions earn their way in from *real recurring review findings*, not speculation (see `core/companion/docs/WORKFLOW.md` §5). Briefly: what recurring mistake(s) would this catch, and roughly how often have you actually hit them on a real project? Optional, if you know it: which model/agent generated the strays it catches, and roughly when (`Model provenance: <model family>, 2026-Q2`) — helps separate durable discipline from one model generation's tics.

**What it would contain**
- `convention_map` bullets (glob → rule):
- `security_map` entries, if any:
- Mechanical checks (grep / semgrep), if applicable:

**Have you used Sysop on the project this came from?**
Helps gauge whether the conventions are promotion-grade vs. speculative.

**Anything else**
