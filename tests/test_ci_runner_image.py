"""The merge gate's pinned runner image carries a review date (`Q-556`, Phase 342).

Phase 315 moved every job from the floating `ubuntu-latest` to the pinned `ubuntu-24.04-arm`.
A floating label maintains itself; a pinned one is eventually retired, and nothing bumps it. A
retired label plausibly leaves the required `pytest` check waiting for a runner that never comes
(the `Q-556` entry marked GitHub's exact behaviour unverified), and a check that never reports
is the failure the workflow's own header names as blocking every PR.

So every pinned GitHub-hosted Ubuntu label in the workflow must appear in `REVIEW_BY` below,
and the suite fails on the review date. **That is a deliberate time bomb, and the trade is
chosen:** from 00:00 UTC on the date, every PR's required check is red until someone bumps the
label or re-dates it. The workflow header's own warning (`Q-427`) is about a date-dependent test
that reddened PRs and was read as their cause; this one names itself and its fix, which that one
did not. Its alternative was a dated note, which depends on someone reading it.

The dates sit before GitHub's deprecation clock can start. Its runner-images support policy
keeps at most two GA images and begins deprecating the oldest label once the newest OS image
label goes GA (`actions/runner-images`, README § *Support Policy*, read 2026-09-28). That day
26.04 was GA and 22.04's deprecation had begun (the repository's announcements, not the
README), which left 24.04 the oldest supported. **The date
assumes GitHub makes only LTS releases GA**, which its history supports but the policy does not
say: an interim release (26.10, 27.04) going GA would start 24.04's clock sooner. Ubuntu 28.04
is not released before April 2028.

When this fails: check `actions/runner-images` for the current GA Ubuntu arm64 label, bump
every `runs-on:` in `.github/workflows/tests.yml` to it, and add that label here with its own
date and the day you read the policy. Re-dating the existing label instead is legitimate only
when the policy page says the image is not yet being deprecated; update `read_on` with it.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "tests.yml"

#: label -> (review by, the day GitHub's support policy was read to choose that date)
REVIEW_BY = {
    "ubuntu-24.04-arm": (datetime.date(2028, 4, 1), datetime.date(2026, 9, 28)),
}
#: A review date further than this from the policy read it rests on is a guess, not a reading.
MAX_HORIZON = datetime.timedelta(days=3 * 365)

_PINNED_UBUNTU = re.compile(r"^ubuntu-\d{2}\.\d{2}(-arm)?$", re.I)
_PLAIN_LABEL = re.compile(r"^[A-Za-z0-9._-]+$")


def runs_on_values(text: str) -> list[object]:
    """Every job's `runs-on:` value, read the way GitHub reads the file: as YAML. A line
    reader missed a flow-style job, a quoted key and `runs-on :` (Phase 342's round 2), and
    refused a `runs-on:` line inside a `run: |` script. A job with no `runs-on` (a reusable
    workflow call) contributes nothing."""
    doc = yaml.safe_load(text) or {}
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict):
        return []
    return [job["runs-on"] for job in jobs.values()
            if isinstance(job, dict) and "runs-on" in job]


def runner_image_problems(text: str, today: datetime.date) -> list[str]:
    problems = []
    values = runs_on_values(text)
    if not values:
        problems.append("the workflow has no job `runs-on:` this check can read")
    for value in values:
        # A list, a mapping or an expression is refused rather than skipped: a pin this
        # check cannot see is a pin it cannot date.
        if not isinstance(value, str) or not _PLAIN_LABEL.match(value):
            problems.append(
                f"`runs-on: {value!r}` is not a single plain label, so this check cannot read "
                "the image it selects; write it as one label, or teach this check the form"
            )
            continue
        if not _PINNED_UBUNTU.match(value):
            continue
        entry = REVIEW_BY.get(value.lower())
        if entry is None:
            problems.append(
                f"`runs-on: {value}` is a pinned image with no review date in REVIEW_BY; "
                "add one from GitHub's runner-images support policy"
            )
            continue
        due, read_on = entry
        if read_on > today:
            problems.append(f"`runs-on: {value}`'s policy read {read_on.isoformat()} is in the future")
        if due - read_on > MAX_HORIZON:
            problems.append(
                f"`runs-on: {value}`'s review date {due.isoformat()} is more than "
                f"{MAX_HORIZON.days} days past the policy read it rests on ({read_on.isoformat()})"
            )
        if today >= due:
            problems.append(
                f"`runs-on: {value}` passed its review date {due.isoformat()}; see this "
                "module's docstring for the bump"
            )
    return problems


def test_every_pinned_runner_image_is_inside_its_review_date():
    assert runner_image_problems(WORKFLOW.read_text(encoding="utf-8"),
                                 datetime.date.today()) == []


def test_every_label_the_workflow_uses_is_one_this_module_can_date():
    """Each job's `runs-on:` is either a dated pin or a floating label. A floating label needs
    no date, which is the half of the trade Phase 315 gave up."""
    values = runs_on_values(WORKFLOW.read_text(encoding="utf-8"))
    assert len(values) >= 2, values
    assert all(isinstance(v, str) and (v in REVIEW_BY or (_PLAIN_LABEL.match(v)
               and not _PINNED_UBUNTU.match(v))) for v in values), values


EARLY = datetime.date(2026, 10, 1)


def _job(runs_on: str) -> str:
    return "on: push\njobs:\n  a:\n    runs-on: " + runs_on + "\n    steps: []\n"


@pytest.mark.parametrize("workflow", [
    _job("ubuntu-30.04-arm"),
    _job("ubuntu-30.04"),
    _job("Ubuntu-30.04-ARM"),
    _job("[ubuntu-30.04-arm]"),
    _job("${{ matrix.os }}"),
    _job(""),
    "jobs:\n  a:\n    runs-on:\n      - ubuntu-30.04-arm\n",
    "jobs:\n  a: {runs-on: ubuntu-30.04-arm, steps: []}\n",
    'jobs:\n  a:\n    "runs-on": ubuntu-30.04-arm\n',
    "jobs:\n  a:\n    runs-on : ubuntu-30.04-arm\n",
    "jobs:\n  a:\n    ? runs-on\n    : ubuntu-30.04-arm\n",
    "jobs:\n  a:\n    runs-on:\n      group: big\n",
    "jobs: {}\n",
    _job("ubuntu 30.04-arm"),
], ids=["undated-arm", "undated-x64", "undated-uppercase", "flow-list", "expression", "empty",
        "block-list", "flow-job", "quoted-key", "space-before-colon", "explicit-key",
        "group-form", "no-jobs", "space-in-label"])
def test_the_tripwire_refuses_a_pin_it_cannot_date(workflow):
    """Round 3: on a one-job fixture, a reader that silently dropped a form still failed, on
    the "no job" arm, so the refusal arm could vanish unseen. The bad job is paired here with
    a plain floating one, and the problem must be something other than "no job"."""
    paired = workflow.replace("jobs:\n", "jobs:\n  z:\n    runs-on: ubuntu-latest\n", 1)
    for text in (workflow, paired):
        problems = runner_image_problems(text, EARLY)
        assert problems, text
        if workflow != "jobs: {}\n":
            assert any("no job" not in p for p in problems), (text, problems)


def test_the_tripwire_fires_on_its_date_and_reads_what_it_should():
    text = WORKFLOW.read_text(encoding="utf-8")
    for label, (due, _) in REVIEW_BY.items():
        assert runner_image_problems(text, due - datetime.timedelta(days=1)) == []
        assert runner_image_problems(text, due), f"{label}: no failure on its review date"
    assert runner_image_problems(_job("'ubuntu-24.04-arm'  # pinned"), EARLY) == []
    assert runner_image_problems(_job("ubuntu-latest"), datetime.date(2099, 1, 1)) == []
    script = ("jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - run: |\n"
              "          echo 'runs-on: ${{ matrix.os }}'\n")
    assert runner_image_problems(script, EARLY) == [], "a runs-on inside a script was refused"


def test_a_review_date_must_rest_on_a_recent_past_policy_read():
    """Round 1 re-dated the pin to 2099 with every check green; round 2 then moved the policy
    read into the future alongside it. The horizon itself is pinned here too."""
    assert MAX_HORIZON == datetime.timedelta(days=1095)
    for label, (due, read_on) in REVIEW_BY.items():
        assert due - read_on <= MAX_HORIZON, label
    saved = dict(REVIEW_BY)
    try:
        for bad in ((datetime.date(2099, 1, 1), datetime.date(2026, 9, 28)),
                    (datetime.date(2099, 1, 1), datetime.date(2097, 1, 1)),
                    (datetime.date(2029, 9, 28), datetime.date(2026, 9, 27)),
                    (datetime.date(2026, 9, 1) + datetime.timedelta(days=1096),
                     datetime.date(2026, 9, 1)),
                    (datetime.date(2027, 1, 1), EARLY + datetime.timedelta(days=1))):
            REVIEW_BY["ubuntu-24.04-arm"] = bad
            assert runner_image_problems(WORKFLOW.read_text(encoding="utf-8"), EARLY), bad
        REVIEW_BY["ubuntu-24.04-arm"] = (datetime.date(2026, 9, 1) + MAX_HORIZON,
                                         datetime.date(2026, 9, 1))
        assert runner_image_problems(WORKFLOW.read_text(encoding="utf-8"), EARLY) == []
    finally:
        REVIEW_BY.clear()
        REVIEW_BY.update(saved)
