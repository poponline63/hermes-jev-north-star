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
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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


class _JevEndpoint(BaseHTTPRequestHandler):
    """A stand-in for TypeSafe's System One: same request, same answer shape."""

    done = 0.9
    weakest = ""
    fail = False
    proven: list = []          # requirement texts the stand-in marks as met

    def do_POST(self):  # noqa: N802 - the name is the protocol
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        questions = payload.get("questions") or {}
        if self.fail:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        answers = {}
        if "done" in questions:
            answers["done"] = {"type": "noul", "noul": self.done}
        if "progress" in questions:
            levels = questions["progress"].get("criteria") or []
            top = len(levels) - 1
            answers["progress"] = {
                "type": "score", "score": self.done * top,
                "legend": {str(i): lvl for i, lvl in enumerate(levels)},
                "probabilities": {str(i): (1.0 if i == top else 0.0) for i in range(len(levels))},
                "confidence": 0.8}
        if "weakest" in questions and self.weakest:
            answers["weakest"] = {"type": "choice", "choice": self.weakest,
                                  "probabilities": {self.weakest: 0.7}, "confidence": 0.7}
        for key, question in questions.items():
            if key.startswith("met_") and question.get("type") == "noul":
                text = str(question.get("instructions") or "")
                hit = any(p and p in text for p in self.proven)
                answers[key] = {"type": "noul", "noul": 0.9 if hit else 0.1,
                                "confidence": 0.85}
        body = json.dumps({"model": "jev-latest", "answers": answers,
                           "usage": {"input_tokens": 41, "output_tokens": 9}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # the test output stays readable
        pass


def judge_cmd(path: Path) -> str:
    """Quote both halves: the interpreter path can contain a space, and this runs through a
    shell (that is the tool's documented contract for --judge)."""
    return f'"{sys.executable}" "{path}"'


def run(*args: str, stdin: str = "", home: Path, expect: int | None = None,
        env_extra: dict | None = None, script: Path | None = None):
    env = dict(os.environ, NORTH_STAR_HOME=str(home), HERMES_HOME=str(home))
    env.pop("TYPESAFE_API_KEY", None)
    env.update(env_extra or {})
    proc = subprocess.run([sys.executable, str(script or TOOL), *args], input=stdin,
                          capture_output=True,
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
              "no judge was used" in out and "Start with:" in out, out[:400])
        check("with no key it says how to get a judge", "TYPESAFE_API_KEY" in out, out[:400])
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

        # 13. the Jev judge, against a stand-in for the System One endpoint ------------------
        judge = TOOL.parent / "jev_judge.py"
        check("the bundled Jev judge ships with the skill", judge.exists(), str(judge))

        code, out = run("--available", home=home, expect=1, script=judge)
        check("no key means the judge reports itself unavailable", "key: no" in out, out[:200])
        check("no key means the gate stays deterministic",
              "no judge was used" in run("gate", "demo", home=home, expect=1)[1])
        code, out = run("--available", home=home, expect=0, script=judge,
                        env_extra={"TYPESAFE_API_KEY": "test-key"})
        check("with a key the judge reports itself available", "key: yes" in out, out[:200])

        server = HTTPServer(("127.0.0.1", 0), _JevEndpoint)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        endpoint = {"TYPESAFE_API_KEY": "test-key",
                    "TYPESAFE_BASE_URL": f"http://127.0.0.1:{port}/v1/systemone"}
        try:
            # not met, and the judge names the requirement it judges furthest away
            _JevEndpoint.done = 0.05
            _JevEndpoint.weakest = "the release page carries the same version the README names"
            _JevEndpoint.proven = ["the documented install command works on a clean machine",
                                   "a wrong input produces a clear error instead of a traceback"]
            code, out = run("gate", "demo", home=home, expect=1, env_extra=endpoint)
            check("a Jev 'not met' keeps the run going", "Goal not met" in out, out[:300])
            check("Jev's weakest requirement is the one named",
                  "the release page carries the same version" in out, out[:400])
            check("the judge's numbers are shown, not hidden",
                  "done 0.05" in out and "jev-latest" in out and "41+9 tokens" in out, out[:400])
            # the gap this run exposed: a run must be able to see what is ALREADY proven
            check("what is proven is listed", "Already shown to hold (2 of 4)" in out, out[:500])
            check("the proven requirement text is printed",
                  "the documented install command works on a clean machine" in out, out[:500])
            check("what is still unproven is listed", "Still unproven (2 of 4)" in out, out[:500])

            # the judge naming a weakest it also marked proven is a contradiction, not a verdict
            _JevEndpoint.weakest = "the documented install command works on a clean machine"
            code, out = run("gate", "demo", home=home, expect=1, env_extra=endpoint)
            check("a judge that contradicts itself says so",
                  "its answers disagree" in out, out[:500])
            _JevEndpoint.weakest = "the release page carries the same version the README names"

            # met: Jev answers that nothing is material, which is what a finished goal gets
            _JevEndpoint.done = 0.93
            _JevEndpoint.weakest = ""
            code, out = run("gate", "demo", home=home, expect=0, env_extra=endpoint)
            check("a Jev 'met' ends the run", out.startswith("DONE"), out[:200])
            check("the done line carries the judge's reasoning", "done 0.93" in out, out[:200])

            # the endpoint breaks: never pass
            _JevEndpoint.fail = True
            code, out = run("gate", "demo", home=home, expect=1, env_extra=endpoint)
            check("an endpoint that errors never passes", "could not reach its judge" in out,
                  out[:300])
            _JevEndpoint.fail = False
        finally:
            server.shutdown()
            server.server_close()

        # an explicitly requested judge that cannot answer must not fall back to "fine"
        code, out = run("gate", "demo", "--judge", "jev", home=home, expect=1)
        check("--judge jev with no key fails closed", "could not reach its judge" in out, out[:300])

        code, out = run("gate", "demo", "--no-judge", home=home, expect=1)
        check("--no-judge says plainly that nothing ranked the work",
              "No judge is configured" in out, out[:300])
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
