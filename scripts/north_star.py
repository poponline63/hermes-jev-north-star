#!/usr/bin/env python3
"""north_star.py - write down a finish line an agent can actually drive.

A north star is a goal plus the states that must be true for it to be met, and a way to see
each one. This tool keeps the whole loop honest:

  set       write the star, validated. A star that cannot be checked is refused.
  check     re-validate an existing star, or a star file, without saving anything.
  prompt    print the goal prompt for a run, generated from the star.
  evidence  append one line of real result to the run's evidence file.
  gate      judge the run: exit 0 = goal met, exit 1 = keep going, stdout is the next step.

No dependencies, no network, no model required. The only thing that touches the network is a
judge command you supply yourself (--judge), and the tool works fine without one.

State lives in $NORTH_STAR_HOME (default ~/.hermes/north-star):
  stars/<name>.json     the stars themselves
  state/<name>.md       the evidence file a run keeps as it works
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_FIELDS = ("goal", "for_whom", "requirements", "checks", "out_of_scope",
                 "stop_rule", "first_action", "ground_truth", "gates")

# Words that describe a mood rather than a state. A star built from these can never be judged,
# so the tool asks for the thing the owner would point at instead.
MOOD_WORDS = ("polished", "seamless", "robust", "world-class", "production-ready",
              "better ux", "works well", "clean up", "more professional", "optimized",
              "best practices", "modern", "scalable")

# Verbs that usually mean the check is observable. Used only to nudge, never to block.
OBSERVABLE_HINTS = ("run ", "open ", "read ", "compare", "check", "test", "print", "log",
                    "curl", "grep", "diff", "look at", "measure", "count", "purchase", "sign",
                    "upload", "download", "select", "query", "poll", "confirm", "inspect",
                    "paste", "note the", "list the")

GAP = ("(fill this in: repo + branch + remote, host + access + ports, where credentials live "
       "and the rule about them, invariants you have corrected before)")

# The prompt is pasted into a run whose working directory is not this one, so every command it
# prints has to resolve anyway. Forward slashes keep it usable from cmd, bash and POSIX shells.
TOOL = Path(__file__).resolve()


def tool_cmd(*args: str) -> str:
    return " ".join([f'"{Path(sys.executable).as_posix()}"', f'"{TOOL.as_posix()}"', *args])


def judge_script() -> Path:
    return TOOL.parent / "jev_judge.py"


def judge_cmd() -> str:
    """The judge is its own script, not a subcommand of this one."""
    return " ".join([f'"{Path(sys.executable).as_posix()}"',
                     f'"{judge_script().as_posix()}"'])


def jev_available() -> bool:
    """Is a TypeSafe key configured? Asked in-process: a subprocess probe depends on how the
    local shell resolves `python3`, which is exactly the kind of thing that fails quietly."""
    script = judge_script()
    if not script.exists():
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("north_star_jev_judge", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return bool(module.api_key())
    except Exception:
        return False


def resolve_judge(value: Optional[str]) -> Tuple[Optional[str], str]:
    """Turn a judge name into a command. Returns (command, note).

    "jev"  the bundled Jev judge (TypeSafe System One).
    "auto" Jev when a key is configured, otherwise no judge at all.
    Anything else is already a command.
    """
    value = (value or "").strip()
    if not value:
        return None, ""
    if value not in ("jev", "auto"):
        return value, ""
    script = judge_script()
    if not script.exists():
        if value == "jev":
            raise SystemExit(f"the bundled Jev judge is missing: {script}")
        return None, ""
    command = judge_cmd()
    if value == "jev":
        return command, ""
    if jev_available():
        return command, ""
    return None, ("No TypeSafe API key is configured, so no judge was used. Set "
                  "TYPESAFE_API_KEY to have Jev rank the requirements.")


# ── storage ───────────────────────────────────────────────────────────────

def home_dir() -> Path:
    env = os.environ.get("NORTH_STAR_HOME")
    return Path(env).expanduser() if env else Path.home() / ".hermes" / "north-star"


def stars_dir(create: bool = False) -> Path:
    d = home_dir() / "stars"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def state_dir(create: bool = False) -> Path:
    d = home_dir() / "state"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def star_path(name: str) -> Path:
    return stars_dir(True) / f"{slug(name)}.json"


def state_path(name: str) -> Path:
    return state_dir(True) / f"{slug(name)}.md"


def slug(name: str) -> str:
    clean = re.sub(r"[^a-z0-9._-]+", "-", str(name or "").strip().lower()).strip("-")
    if not clean:
        raise SystemExit("a star needs a name")
    return clean


def load_star(name: str) -> Optional[Dict[str, Any]]:
    path = star_path(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{path} is not readable JSON: {exc}")


def save_star(name: str, star: Dict[str, Any]) -> Path:
    path = star_path(name)
    path.write_text(json.dumps(star, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_json(source: str) -> Dict[str, Any]:
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise SystemExit(f"that is not valid JSON: {exc}")


# ── validation: what makes a star drivable ────────────────────────────────

def validate_star(star: Dict[str, Any]) -> List[str]:
    """Return the reasons this star cannot drive a run. Empty means it can."""
    problems: List[str] = []
    star = star or {}

    goal = str(star.get("goal") or "").strip()
    if not goal:
        problems.append("goal: missing. One sentence, the finished state seen from the outside.")
    elif len(goal) > 300:
        problems.append("goal: over 300 characters. It is a finish line, not a description.")
    elif (mood := next((w for w in MOOD_WORDS if w in goal.lower()), "")):
        problems.append(f"goal: '{mood}' is a mood, not a state. Say what would be true instead.")

    if not str(star.get("for_whom") or "").strip():
        problems.append("for_whom: missing. Who is this finished for?")

    requirements = [str(r).strip() for r in (star.get("requirements") or []) if str(r).strip()]
    if not requirements:
        problems.append("requirements: none. A goal with no stated states cannot be judged.")
    if len(requirements) > 12:
        problems.append(f"requirements: {len(requirements)}. Past 12 this is a plan, not a star.")
    for req in requirements:
        if len(req) > 200:
            problems.append(f"requirement too long ({len(req)} chars): {req[:60]}...")
        if (mood := next((w for w in MOOD_WORDS if w in req.lower()), "")):
            problems.append(f"requirement '{req[:40]}...': '{mood}' cannot be pointed at.")

    checks = star.get("checks") or {}
    if requirements and not isinstance(checks, dict):
        problems.append("checks: must be an object keyed by the exact requirement text.")
        checks = {}
    for req in requirements:
        check = str(checks.get(req) or "").strip()
        if not check:
            problems.append(f"checks: no way to see that this is true -> {req}")
        elif check.lower() == req.lower():
            problems.append(f"checks: the requirement is stated twice, nothing is verified -> {req}")
        elif len(check.split()) < 3:
            problems.append(f"checks: '{check}' is too short to verify anything -> {req}")
    for key in list(checks):
        if key not in requirements:
            problems.append(f"checks: '{key[:50]}...' matches no requirement exactly. "
                            "Copy the requirement text verbatim.")

    if not (star.get("out_of_scope") or []):
        problems.append("out_of_scope: empty. The boundary is what stops a run wandering.")
    if not str(star.get("stop_rule") or "").strip():
        problems.append("stop_rule: missing. When does the run stop and hand back?")
    if not str(star.get("first_action") or "").strip():
        problems.append("first_action: missing. What is the first thing it should do?")

    gates = star.get("gates") or []
    if gates and not isinstance(gates, list):
        problems.append("gates: must be a list of shell commands that exit 0 when true.")
    required = [f for f in star if f not in SCHEMA_FIELDS]
    if required:
        problems.append(f"unknown fields: {', '.join(sorted(required))}. "
                        "An unknown field is a note to yourself that nobody reads.")
    return problems


def check_verifiability(star: Dict[str, Any]) -> List[str]:
    """Soft advice, never a refusal: checks that name no observable action."""
    advice = []
    for req in (star.get("requirements") or []):
        check = str((star.get("checks") or {}).get(req) or "")
        if check and not any(h in check.lower() for h in OBSERVABLE_HINTS) and "`" not in check:
            advice.append(f"weak check (name the command or artifact): {req}")
    return advice


# ── the goal prompt ───────────────────────────────────────────────────────

def build_prompt(name: str, star: Dict[str, Any]) -> str:
    """The run prompt, generated from the star so the two can never drift apart."""
    star = star or {}
    checks = star.get("checks") or {}
    lines = ["GOAL", (star.get("goal") or GAP).rstrip(".") + "."]
    if star.get("for_whom"):
        lines[-1] = f"{lines[-1]} Finished for: {str(star['for_whom']).rstrip('.')}."

    lines += ["", "GROUND TRUTH - do not re-derive any of this"]
    truth = [str(t).strip() for t in (star.get("ground_truth") or []) if str(t).strip()]
    lines += [f"- {t}" for t in truth] or [f"- {GAP}"]
    lines += [f"- The finish line is the north star '{name}' "
              f"(re-read it with: {tool_cmd('show', name)}). Ground truth in this prompt "
              "outranks anything the run later infers."]

    lines += ["", "WHAT MUST BE TRUE, AND HOW EACH ONE IS SEEN"]
    for index, req in enumerate(star.get("requirements") or [], start=1):
        lines.append(f"{index}. {req}")
        lines.append(f"   Done when: {checks.get(req) or GAP}")

    if star.get("out_of_scope"):
        lines += ["", "NOT THIS"]
        lines += [f"- {line}" for line in star["out_of_scope"]]

    lines += ["", "STOP", star.get("stop_rule") or GAP]
    if star.get("first_action"):
        lines += ["", "FIRST STEP", str(star["first_action"])]

    lines += ["", "CHECK BEFORE SAYING DONE",
              f"- Keep this run's evidence in {state_path(name)}: append one short line per real "
              "result, with the command and what it actually printed "
              f"({tool_cmd('evidence', name, '--add', chr(34) + '...' + chr(34))}). That file is "
              "what the gate reads, and an empty file means there is nothing to judge.",
              f"- Run `{tool_cmd('gate', name)}`. Exit 0 means every requirement above is met. "
              "Anything else names the weakest requirement and the next step. Keep going until "
              "it exits 0 or the stop rule fires.",
              "- Re-read this prompt before believing a finding that feels convenient."]

    lines += ["", "NEVER CLAIM WITHOUT PROOF",
              "- Do not report a requirement as met without the verification named next to it. "
              "An accepted request is not a completed action, and a queued job is not a result."]

    lines += ["", "REPORT",
              "- What changed, the tallies, and the next real constraint. Push to the stated "
              "remote when done."]
    return "\n".join(lines).strip() + "\n"


# ── the gate ──────────────────────────────────────────────────────────────

def run_shell_gates(commands: List[str], cwd: Optional[str] = None,
                    timeout_s: int = 600) -> Tuple[bool, str]:
    """Deterministic checks first: they cost nothing and cannot be argued with."""
    for command in commands or []:
        try:
            proc = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return False, f"gate timed out after {timeout_s}s: {command}"
        if proc.returncode != 0:
            tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-2000:]
            return False, f"gate failed (exit {proc.returncode}): {command}\n{tail}"
    return True, ""


def run_judge(command: str, name: str, star: Dict[str, Any], state_text: str,
              timeout_s: int = 600) -> Tuple[Optional[bool], str, Dict[str, Any], str]:
    """Ask a judge command whether the goal is met.

    The judge gets the star and the state as JSON on stdin. It answers on stdout with
    {"met": true|false, "weakest": "<requirement, optional>"}. Printing nothing at all means
    the exit code decides: 0 = met, anything else = not met. A judge that prints text without a
    readable verdict is treated as unreachable, because a broken answer must never read as
    agreement. Any command works: a script, a model call, or another agent. This tool ships no
    judge of its own.
    """
    payload = {"name": name, "goal": star.get("goal"),
               "requirements": star.get("requirements") or [],
               "checks": star.get("checks") or {}, "state": state_text}
    try:
        proc = subprocess.run(command, shell=True, input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return None, "", {}, f"the judge timed out after {timeout_s}s"
    out = (proc.stdout or "").strip()
    met, weakest, intended, extra = parse_judge_output(out)
    if met is None:
        if intended:
            # It tried to answer and the answer is unreadable. Fail closed rather than
            # reading a broken verdict as agreement.
            return None, "", {}, f"the judge's output is not a readable verdict: {out[-400:]}"
        if out:
            return None, "", {}, ("the judge printed text but no verdict. Expected "
                                  '{"met": true|false, "weakest": "..."} on stdout. A bare exit '
                                  f"code is only honoured when the judge prints nothing: {out[-400:]}")
        if proc.returncode not in (0, 1):
            stderr = (proc.stderr or "").strip()[-400:]
            return None, "", {}, f"the judge exited {proc.returncode}: {stderr or out or 'no output'}"
        met = proc.returncode == 0
    return met, weakest, extra, ""


def parse_judge_output(out: str) -> Tuple[Optional[bool], str, bool, Dict[str, Any]]:
    """Read a judge's answer. Returns (met, weakest, intended_to_answer, everything_else).

    Extra keys are kept rather than dropped: a judge that reports why it decided (a done
    probability, a confidence, a model name) should have that shown, not hidden behind a
    boolean.
    """
    out = (out or "").strip()
    if not out:
        return None, "", False, {}
    candidates = [out]
    if "{" in out and "}" in out:
        candidates.append(out[out.index("{"):out.rindex("}") + 1])
    for text in candidates:
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            extra = {k: v for k, v in parsed.items() if k not in ("met", "weakest")}
            if "met" in parsed:
                return bool(parsed.get("met")), str(parsed.get("weakest") or ""), True, extra
            return None, "", True, extra
    if re.search(r"[\"']?met[\"']?\s*[:=]", out, re.IGNORECASE):
        return None, "", True, {}
    return None, "", False, {}


def judge_line(extra: Dict[str, Any]) -> str:
    """One line saying how the judge reached its answer, never just a boolean."""
    if not extra:
        return ""
    bits = []
    if extra.get("done") is not None:
        need = extra.get("done_needs")
        bits.append(f"done {extra['done']}" + (f" (needs {need})" if need is not None else ""))
    if extra.get("progress") is not None:
        bits.append(f"progress {extra['progress']}")
    confidence = extra.get("confidence") or {}
    if isinstance(confidence, dict) and confidence.get("done") is not None:
        bits.append(f"confidence {confidence['done']}")
    if extra.get("model"):
        bits.append(str(extra["model"]))
    usage = extra.get("usage") or {}
    if isinstance(usage, dict) and usage.get("input_tokens"):
        bits.append(f"{usage['input_tokens']}+{usage.get('output_tokens', 0)} tokens")
    return ("Judge: " + ", ".join(bits) + "\n") if bits else ""


def run_gate(name: str, state_text: str, *, judge: Optional[str] = None,
             cwd: Optional[str] = None, timeout_s: int = 600) -> Dict[str, Any]:
    star = load_star(name)
    if not star:
        return {"ok": False, "exit_code": 2,
                "text": f"no north star named {name!r}. Set one first: "
                        f"python3 scripts/north_star.py set {name} --from-json <file>"}

    problems = validate_star(star)
    if problems:
        return {"ok": False, "exit_code": 2, "gate": "star",
                "text": "this star is not drivable:\n- " + "\n- ".join(problems)}

    if not (state_text or "").strip():
        path = state_path(name)
        state_text = path.read_text(encoding="utf-8", errors="replace")[-20000:] \
            if path.exists() else ""

    passed, detail = run_shell_gates(star.get("gates") or [], cwd=cwd, timeout_s=timeout_s)
    if not passed:
        return {"ok": True, "exit_code": 1, "gate": "shell", "verdict": "continue",
                "text": detail, "next_prompt": detail}

    if not (state_text or "").strip():
        # A verdict on nothing is noise, not a judgement.
        path = state_path(name)
        text = ("Nothing to judge: no state was passed and the run's evidence file is empty:\n"
                f"  {path}\n"
                "Append what changed to that file (or pass --state / --state-file), then run "
                f"the gate again:\n  {tool_cmd('gate', name)}")
        return {"ok": True, "exit_code": 1, "gate": "state", "verdict": "continue",
                "text": text, "next_prompt": text}

    requirements = star.get("requirements") or []
    weakest = ""
    judge, judge_note = resolve_judge(judge)
    extra: Dict[str, Any] = {}
    if judge:
        met, weakest, extra, error = run_judge(judge, name, star, state_text, timeout_s=timeout_s)
        if error:
            # A gate that cannot reach its judge must never pass silently.
            text = (f"The gate could not reach its judge, so it is not claiming done.\n{error}\n"
                    "Fix the judge, then run the gate again.")
            return {"ok": False, "exit_code": 1, "gate": "judge", "verdict": "continue",
                    "text": text, "next_prompt": text}
        if met:
            text = (f"DONE: {star.get('goal')}\n{judge_line(extra)}"
                    f"Evidence file: {state_path(name)}")
            return {"ok": True, "exit_code": 0, "gate": "judge", "verdict": "done", "text": text,
                    "judge": extra, "next_prompt": ""}
    else:
        # No judge: the gate can prove nothing about the fuzzy requirements, so it does not
        # pretend the goal is met. It points at the work instead.
        met = False

    if not weakest:
        weakest = requirements[0] if requirements else ""
    check = (star.get("checks") or {}).get(weakest) or "(no check recorded)"
    lines = [f"Goal not met: {star.get('goal')}"]
    if not judge:
        lines.append(judge_note or
                     "No judge is configured (--judge), so nothing here ranks the requirements. "
                     "Take the first one that is not proven yet.")
    elif extra:
        lines.append(judge_line(extra).strip())
    if weakest:
        label = "Weakest requirement" if judge else "Start with"
        lines.append(f"{label}: {weakest}")
        lines.append(f"Done when: {check}")
    lines.append("Do not restate the goal. Do the smallest next step that moves the weakest "
                 "requirement, then run the gate again.")
    lines.append(f"Evidence so far ({state_path(name)}): "
                 f"{len(state_text.splitlines())} line(s).")
    text = "\n".join(lines)
    return {"ok": True, "exit_code": 1, "gate": "judge" if judge else "state",
            "verdict": "continue", "weakest": weakest, "judge": extra, "text": text,
            "next_prompt": text}


# ── CLI ───────────────────────────────────────────────────────────────────

def cmd_set(args: argparse.Namespace) -> int:
    if args.from_json:
        star = read_json(args.from_json)
    elif args.goal:
        star = {"goal": args.goal, "for_whom": args.for_whom or "",
                "requirements": args.require or [],
                "checks": dict(c.split("=", 1) for c in (args.check or []) if "=" in c),
                "out_of_scope": args.not_this or [], "stop_rule": args.stop or "",
                "first_action": args.first or ""}
    else:
        print("give a star with --from-json <file|-> or --goal ...", file=sys.stderr)
        return 2

    problems = validate_star(star)
    if problems:
        print(f"refused: this star cannot drive a run ({len(problems)} problem(s)):", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        print("\nFix these, then save again. A requirement with no way to check it is not a "
              "requirement.", file=sys.stderr)
        return 2

    path = save_star(args.name, star)
    advice = check_verifiability(star)
    keep = {k: star.get(k) for k in SCHEMA_FIELDS if star.get(k) not in (None, "", [], {})}
    print(f"north star '{slug(args.name)}' saved: {path}")
    print(f"{len(keep.get('requirements') or [])} requirements, "
          f"{len(keep.get('checks') or {})} with a stated verification.")
    for line in advice:
        print(f"note: {line}")
    print(f"\nprompt for the run:\n  python3 scripts/north_star.py prompt {slug(args.name)}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    targets: List[Tuple[str, Dict[str, Any]]] = []
    if args.file:
        targets.append((Path(args.file).name, read_json(args.file)))
    elif args.all:
        for path in sorted(stars_dir().glob("*.json")):
            try:
                targets.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError) as exc:
                print(f"{path.stem}: unreadable ({exc})")
    else:
        star = load_star(args.name)
        if star is None:
            print(f"no north star named {args.name!r}", file=sys.stderr)
            return 2
        targets.append((slug(args.name), star))

    worst = 0
    for name, star in targets:
        problems = validate_star(star)
        if problems:
            print(f"{name}: NOT drivable ({len(problems)})")
            for problem in problems:
                print(f"  - {problem}")
            worst = max(worst, 2)
        else:
            print(f"{name}: drivable. {len(star.get('requirements') or [])} requirements, "
                  "each with a verification.")
            for line in check_verifiability(star):
                print(f"  note: {line}")
    return worst


def cmd_list(args: argparse.Namespace) -> int:
    paths = sorted(stars_dir().glob("*.json"))
    if not paths:
        print("No north stars yet. Add one: python3 scripts/north_star.py set <name> "
              "--goal \"...\" --require \"...\"")
        return 0
    for path in paths:
        try:
            star = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"{path.stem}: unreadable")
            continue
        print(f"{path.stem}: {star.get('goal')}")
        for req in star.get("requirements") or []:
            print(f"    - {req}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    star = load_star(args.name)
    if star is None:
        print(f"no north star named {args.name!r}", file=sys.stderr)
        return 2
    print(json.dumps(star, indent=2, ensure_ascii=False))
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    star = load_star(args.name)
    if star is None:
        print(f"no north star named {args.name!r}", file=sys.stderr)
        return 2
    prompt = build_prompt(slug(args.name), star)
    if args.json:
        print(json.dumps({"name": slug(args.name), "prompt": prompt}, indent=2,
                         ensure_ascii=False))
    else:
        print(prompt)
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    if load_star(args.name) is None:
        print(f"no north star named {args.name!r}", file=sys.stderr)
        return 2
    path = state_path(args.name)
    lines = [line for line in (args.add or []) if line.strip()]
    if not lines and not sys.stdin.isatty():
        lines = [line for line in sys.stdin.read().splitlines() if line.strip()]
    if not lines:
        print("nothing to add: use --add \"one line\" or pipe the lines in", file=sys.stderr)
        return 2
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    with path.open("a", encoding="utf-8") as fh:
        if not existing:
            fh.write(f"# evidence for north star {slug(args.name)}\n")
        elif not existing.endswith("\n"):
            fh.write("\n")
        for line in lines:
            fh.write(f"- {line.strip()}\n")
    print(f"{len(lines)} line(s) appended to {path}")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    judge = None if args.no_judge else (args.judge or os.environ.get("NORTH_STAR_JUDGE") or "auto")
    result = run_gate(args.name, args.state or (Path(args.state_file).read_text(encoding="utf-8")
                                                if args.state_file else ""),
                      judge=judge, cwd=args.cwd, timeout_s=args.timeout)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result.get("text", ""))
    return int(result.get("exit_code", 1))


def cmd_rm(args: argparse.Namespace) -> int:
    path = star_path(args.name)
    if not path.exists():
        print(f"no north star named {args.name!r}", file=sys.stderr)
        return 2
    path.unlink()
    print(f"removed {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="north_star.py",
        description="Write down a finish line an agent can drive: a star, a prompt, and a gate.")
    parser.add_argument("--home", help="where stars and evidence live "
                                       "(default $NORTH_STAR_HOME or ~/.hermes/north-star)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("set", help="save a star (validated)")
    p.add_argument("name")
    p.add_argument("--from-json", help="a star as JSON, or - for stdin")
    p.add_argument("--goal")
    p.add_argument("--for-whom", dest="for_whom")
    p.add_argument("--require", action="append", help="a requirement (repeatable)")
    p.add_argument("--check", action="append",
                   help="a verification as '<requirement>=<how you see it>' (repeatable)")
    p.add_argument("--not-this", dest="not_this", action="append",
                   help="something this is explicitly not (repeatable)")
    p.add_argument("--stop", help="when the run stops and what it hands back")
    p.add_argument("--first", help="the first thing the run should do")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("check", help="re-validate a star without saving anything")
    p.add_argument("name", nargs="?", default="")
    p.add_argument("--file", help="check a star file instead of a saved star")
    p.add_argument("--all", action="store_true", help="check every saved star")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("list", help="list saved stars")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="print one star as JSON")
    p.add_argument("name")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("prompt", help="print the goal prompt generated from a star")
    p.add_argument("name")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("evidence", help="append a real result to the run's evidence file")
    p.add_argument("name")
    p.add_argument("--add", action="append", help="one line of evidence (repeatable)")
    p.set_defaults(func=cmd_evidence)

    p = sub.add_parser("gate", help="judge the run: exit 0 = goal met, stdout = next step")
    p.add_argument("name")
    p.add_argument("--state", help="the state to judge as a literal string")
    p.add_argument("--state-file", dest="state_file", help="the state to judge, from a file")
    p.add_argument("--judge", default=None,
                   help="a command that decides {'met': bool, 'weakest': str}; 'jev' for the "
                        "bundled Jev judge, 'auto' (default) for Jev when a key is configured. "
                        "Falls back to $NORTH_STAR_JUDGE")
    p.add_argument("--no-judge", dest="no_judge", action="store_true",
                   help="deterministic checks and the evidence file only, no model")
    p.add_argument("--cwd", help="working directory for the gate commands")
    p.add_argument("--timeout", type=int, default=600, help="seconds per gate/judge command")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("rm", help="delete a saved star")
    p.add_argument("name")
    p.set_defaults(func=cmd_rm)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "home", None):
        os.environ["NORTH_STAR_HOME"] = args.home
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
