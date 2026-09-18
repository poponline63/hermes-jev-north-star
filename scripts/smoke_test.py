#!/usr/bin/env python3
"""Every claim the README and SKILL.md make, asserted against the real thing.

Run: python3 scripts/smoke_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "north_star.py"
TEMPLATE = HERE.parent / "templates" / "star.example.json"

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"ok   {label}")
    else:
        print(f"FAIL {label}" + (f"\n     {detail}" if detail else ""))
        FAILURES.append(label)


def judge_cmd(path: Path) -> str:
    """Quote both halves: the interpreter path can contain a space, and this runs through a
    shell (that is the tool's documented contract for --judge)."""
    return f'"{sys.executable}" "{path}"'


def run(*args: str, stdin: str = "", home: Path, expect: int | None = None):
    env = dict(os.environ, NORTH_STAR_HOME=str(home))
    proc = subprocess.run([sys.executable, str(TOOL), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env, cwd=HERE.parent)
    out = (proc.stdout or "") + (proc.stderr or "")
    if expect is not None:
        check(f"exit {expect}: {' '.join(args[:2])}", proc.returncode == expect,
              f"got {proc.returncode}\n{out[:400]}")
    return proc.returncode, out


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="north-star-smoke-"))
    try:
        # 1. the shipped example is drivable
        code, out = run("check", "--file", str(TEMPLATE), home=home, expect=0)
        check("the example template is drivable", "drivable" in out, out[:200])

        # 2. an unjudgeable star is refused, and the reasons are the real ones
        bad = home / "bad.json"
        bad.write_text(json.dumps({
            "goal": "make the app polished", "for_whom": "",
            "requirements": ["better UX", "clean up the code"],
            "checks": {"better UX": "better UX"}, "out_of_scope": [],
            "stop_rule": "", "first_action": ""}), encoding="utf-8")
        code, out = run("set", "bad", "--from-json", str(bad), home=home, expect=2)
        for fragment in ("is a mood", "for_whom: missing", "cannot be pointed at",
                         "stated twice", "no way to see", "out_of_scope: empty",
                         "stop_rule: missing", "first_action: missing"):
            check(f"refusal names: {fragment}", fragment in out, out[:400])
        check("a refused star is not saved", not (home / "stars" / "bad.json").exists())

        # 3. a good star saves, and check agrees
        run("set", "demo", "--from-json", str(TEMPLATE), home=home, expect=0)
        code, out = run("check", "demo", home=home, expect=0)
        check("a saved star re-checks clean", "drivable" in out, out[:200])
        code, out = run("list", home=home, expect=0)
        check("list shows the goal and its requirements",
              "a stranger can install" in out and "install command works" in out, out[:300])

        # 4. the prompt is generated from the star, with every section a run needs
        code, out = run("prompt", "demo", home=home, expect=0)
        for section in ("GOAL", "GROUND TRUTH", "WHAT MUST BE TRUE", "NOT THIS", "STOP",
                        "FIRST STEP", "CHECK BEFORE SAYING DONE", "NEVER CLAIM WITHOUT PROOF",
                        "REPORT"):
            check(f"prompt carries section: {section}", section in out)
        check("prompt names the evidence file", "state/demo.md" in out.replace("\\", "/"),
              out[:400])
        check("prompt carries each requirement's check verbatim",
              "run the install line from the README in a fresh container" in out)
        check("prompt json shape", json.loads(run("prompt", "demo", "--json", home=home)[1])
              .get("name") == "demo")
        # the run that receives this prompt is in another working directory, so every command
        # printed has to resolve from anywhere, not just from the repo root.
        check("prompt names the tool by an absolute path",
              TOOL.resolve().as_posix() in out, out[:300])

        # 5. the gate refuses to judge nothing
        code, out = run("gate", "demo", home=home, expect=1)
        check("an empty evidence file is refused", "Nothing to judge" in out, out[:300])
        check("the refusal names the file", "state" in out and "demo.md" in out, out[:300])

        # 6. evidence in, and the gate has something to work with
        run("evidence", "demo", "--add", "ran the README install line: exit 0", home=home,
            expect=0)
        code, out = run("gate", "demo", home=home, expect=1)
        check("the gate reports the goal is not met", "Goal not met" in out, out[:300])
        check("no judge means no ranking is claimed",
              "No judge is configured" in out and "Start with:" in out, out[:400])
        check("the next step carries the requirement's check",
              "Done when: run the install line" in out, out[:400])

        # 7. a judge that says no is believed, and names the weakest
        judge_no = home / "judge_no.py"
        judge_no.write_text(
            'import json\nprint(json.dumps({"met": False, "weakest": '
            '"the release page carries the same version the README names"}))\n', encoding="utf-8")
        code, out = run("gate", "demo", "--judge", judge_cmd(judge_no), home=home, expect=1)
        check("a judge's 'not met' is honoured", "Weakest requirement" in out
              and "release page" in out, out[:400])

        # 8. a judge that says yes ends the run
        judge_yes = home / "judge_yes.py"
        judge_yes.write_text('import json\nprint(json.dumps({"met": True}))\n', encoding="utf-8")
        code, out = run("gate", "demo", "--judge", judge_cmd(judge_yes), home=home, expect=0)
        check("a judge's 'met' ends the run", out.startswith("DONE"), out[:200])

        # 9. a broken judge never reads as agreement
        judge_broken = home / "judge_broken.py"
        judge_broken.write_text('print("looks fine to me")\n', encoding="utf-8")
        code, out = run("gate", "demo", "--judge", judge_cmd(judge_broken), home=home, expect=1)
        check("an unreadable verdict does not pass", "could not reach its judge" in out,
              out[:400])
        code, out = run("gate", "demo", "--judge", "exit 3", home=home, expect=1)
        check("an unreachable judge does not pass", "could not reach its judge" in out, out[:300])

        # 10. deterministic gates run first and cannot be argued with
        star = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        star["gates"] = ["exit 1"]
        gated = home / "gated.json"
        gated.write_text(json.dumps(star), encoding="utf-8")
        run("set", "gated", "--from-json", str(gated), home=home, expect=0)
        run("evidence", "gated", "--add", "something happened", home=home, expect=0)
        code, out = run("gate", "gated", "--judge", judge_cmd(judge_yes), home=home, expect=1)
        check("a failing shell gate short-circuits the judge", "gate failed (exit 1)" in out,
              out[:300])

        # 11. a missing star is a configuration error, not a verdict
        code, out = run("gate", "nope", home=home, expect=2)
        check("a missing star exits 2", "no north star named" in out, out[:200])

        # 12. stars can be saved from the command line alone
        run("set", "cli", "--goal", "the report ships on a schedule and lands in the inbox",
            "--for-whom", "the operator", "--require", "the job runs unattended for a week",
            "--check", "the job runs unattended for a week=read the scheduler log for seven days",
            "--not-this", "adding new report types", "--stop", "stop when a week passes clean",
            "--first", "print the current scheduler entry", home=home, expect=0)
        code, out = run("check", "cli", home=home, expect=0)
        check("a star built from flags is drivable", "drivable" in out, out[:200])
    finally:
        shutil.rmtree(home, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} of {CHECKS} checks FAILED")
        return 1
    print(f"{CHECKS}/{CHECKS} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
