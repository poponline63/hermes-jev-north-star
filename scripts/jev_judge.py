#!/usr/bin/env python3
"""jev_judge.py - judge a north star with Jev (TypeSafe System One).

A gate can already prove the machine-checkable parts of a goal. What it cannot do is read a run's
messy evidence and decide whether a *fuzzy* requirement is really met: "the round-up arrives as a
whole share", "the customer can complete checkout without writing to us". That judgement is what
this script delegates to Jev, which returns typed answers with a calibrated confidence instead of
prose, so the gate stays code and never reads a model's opinion of its own progress.

It is a drop-in judge for `north_star.py gate --judge`. It reads the same payload on stdin
({"name", "goal", "requirements", "checks", "state"}) and prints one JSON object on stdout:

    {"met": false, "weakest": "<requirement>", "done": 0.07, "progress": 1.61,
     "confidence": {...}, "model": "jev-latest", "usage": {...}}

Asking Jev three things about one state, in one call:

    noul    is EVERY requirement met?                    -> a probability, thresholded
    score   how far along is this, on four levels?       -> a point on the scale
    choice  which requirement is furthest from being met? -> the next thing to work on

Exit codes: 0 met, 1 not met, 2 the judge could not answer (no key, no network, bad reply).
The gate treats 2 as "cannot reach the judge" and never as agreement.

Environment:
    TYPESAFE_API_KEY     the credential. Also read from ~/.hermes/.env
    TYPESAFE_BASE_URL    override the endpoint (tests, a proxy). Default: the public API.
    JEV_MODEL            default jev-latest
    JEV_THRESHOLD        done probability that counts as met. Default 0.60
    JEV_TIMEOUT          seconds per call. Default 30
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
RETRY_STATUS = (429, 529)
USER_AGENT = "hermes-north-star/jev-judge"
PROGRESS_LEVELS = [
    "Nothing usable yet: the work has not started in any real form.",
    "Early partial: some pieces exist but the goal is not reachable yet.",
    "Mostly working with named gaps: the goal is close, specific items remain.",
    "Complete and verified: every requirement is met and the evidence shows it.",
]
NOTHING_MATERIAL = "nothing material: every requirement looks met"


class JudgeError(RuntimeError):
    """Any failure that has to reach the gate with its cause intact."""


# ── credential ────────────────────────────────────────────────────────────

def dotenv_value(name: str, home: Optional[Path] = None) -> str:
    """Read one key from the Hermes env file, so a backend older than the key still finds it."""
    for candidate in (home, Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")):
        if not candidate:
            continue
        path = Path(candidate) / ".env"
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def api_key() -> str:
    return (os.environ.get("TYPESAFE_API_KEY") or dotenv_value("TYPESAFE_API_KEY")).strip()


# ── the one call ──────────────────────────────────────────────────────────

def build_questions(requirements: List[str]) -> Dict[str, Any]:
    questions: Dict[str, Any] = {
        "done": {
            "type": "noul",
            "instructions": "Based only on the evidence in the state, is EVERY requirement of "
                            "the goal met?",
            "criteria": {"true": "All requirements are met and the evidence shows it.",
                         "false": "At least one requirement is unmet, unproven or unverified."},
        },
        "progress": {
            "type": "score",
            "instructions": "How far along is this work, judged only from the evidence?",
            "criteria": PROGRESS_LEVELS,
        },
    }
    if requirements:
        options = {req: req for req in requirements}
        options[NOTHING_MATERIAL] = "No requirement is material; everything is met."
        questions["weakest"] = {"type": "choice",
                                "instructions": "Which requirement is furthest from being met?",
                                "criteria": options}
    return questions


def call_jev(state: Any, questions: Dict[str, Any], *, key: str, url: str, model: str,
             timeout: float, retries: int = 3) -> Dict[str, Any]:
    body = json.dumps({"state": state, "model": model, "questions": questions}).encode("utf-8")
    last = ""
    for attempt in range(max(1, retries)):
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            last = f"HTTP {exc.code}: {detail or exc.reason}"
            if exc.code in RETRY_STATUS and attempt + 1 < retries:
                time.sleep(min(8.0, 0.75 * (2 ** attempt)))
                continue
            raise JudgeError(last) from exc
        except urllib.error.URLError as exc:
            last = f"network: {exc.reason}"
            if attempt + 1 < retries:
                time.sleep(min(8.0, 0.75 * (2 ** attempt)))
                continue
            raise JudgeError(last) from exc
        except ValueError as exc:
            raise JudgeError(f"the endpoint did not return JSON: {exc}") from exc
    raise JudgeError(f"gave up after {retries} attempts ({last})")


# ── reading the answer ────────────────────────────────────────────────────

def read_noul(answer: Dict[str, Any]) -> Tuple[float, float]:
    value = float((answer or {}).get("noul") or 0.0)
    confidence = (answer or {}).get("confidence")
    return value, float(confidence if confidence is not None else abs(value - 0.5) * 2.0)


def read_score(answer: Dict[str, Any]) -> Tuple[Optional[float], float, Dict[str, Any], Dict[str, Any]]:
    answer = answer or {}
    score = answer.get("score")
    return (None if score is None else float(score),
            float(answer.get("confidence") or 0.0),
            answer.get("legend") or {},
            answer.get("probabilities") or {})


def read_choice(answer: Dict[str, Any]) -> Tuple[str, float]:
    answer = answer or {}
    probabilities = answer.get("probabilities") or {}
    confidence = answer.get("confidence")
    if confidence is None:
        confidence = max(probabilities.values()) if probabilities else 0.0
    return str(answer.get("choice") or ""), float(confidence)


def judge(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ask Jev about one state. Returns the verdict the gate prints."""
    key = api_key()
    url = os.environ.get("TYPESAFE_BASE_URL") or DEFAULT_URL
    model = os.environ.get("JEV_MODEL") or "jev-latest"
    threshold = float(os.environ.get("JEV_THRESHOLD") or 0.60)
    score_floor = float(os.environ.get("JEV_SCORE_FLOOR") or 0.50)
    timeout = float(os.environ.get("JEV_TIMEOUT") or 30)

    if not key:
        raise JudgeError(
            "no TypeSafe API key: set TYPESAFE_API_KEY, or put it in ~/.hermes/.env, or run the "
            "gate without a judge (it will say plainly that nothing ranks the requirements)")

    state = payload.get("state") or ""
    requirements = [str(r) for r in (payload.get("requirements") or [])]
    goal = payload.get("goal") or ""

    # The judge is asked about evidence, not about itself, so the state carries the star too.
    state_text = (f"GOAL: {goal}\n\n"
                  f"REQUIREMENTS:\n" + "\n".join(f"- {r}" for r in requirements) +
                  f"\n\nEVIDENCE FROM THE RUN:\n{state}")

    questions = build_questions(requirements)
    raw = call_jev(state_text, questions, key=key, url=url, model=model, timeout=timeout)
    answers = raw.get("answers") or {}

    done, done_confidence = read_noul(answers.get("done") or {})
    progress, progress_confidence, legend, probabilities = read_score(answers.get("progress") or {})
    weakest, weakest_confidence = read_choice(answers.get("weakest") or {})

    levels = list(legend.values())
    top_index = str(len(levels) - 1) if levels else ""
    top_probability = float(probabilities.get(top_index) or 0.0) if top_index else 0.0

    blockers: List[str] = []
    if done < threshold:
        blockers.append(f"done probability {done:.2f} < {threshold:.2f}")
    if not levels:
        blockers.append("no progress levels returned")
    elif top_probability < score_floor:
        blockers.append(f"top progress level probability {top_probability:.2f} < {score_floor:.2f}")
    if weakest and weakest != NOTHING_MATERIAL:
        blockers.append(f"weakest requirement: {weakest}")
    met = not blockers and done >= threshold

    return {
        "met": met,
        "weakest": "" if weakest == NOTHING_MATERIAL else weakest,
        "done": round(done, 4),
        "done_needs": threshold,
        "progress": progress,
        "top_progress_probability": round(top_probability, 4),
        "confidence": {"done": round(done_confidence, 4),
                       "progress": round(progress_confidence, 4),
                       "weakest": round(weakest_confidence, 4)},
        "blockers": blockers,
        "model": raw.get("model") or model,
        "usage": raw.get("usage") or {},
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0

    if "--available" in argv:
        print("key: yes" if api_key() else "key: no")
        return 0 if api_key() else 1

    raw = sys.stdin.read() if not argv else ""
    if argv:  # explicit file argument: --state-file <path>, otherwise stdin
        if argv[0] in ("--state-file", "--star-file") and len(argv) > 1:
            raw = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
        else:
            print(f"unexpected arguments: {' '.join(argv)}", file=sys.stderr)
            return 2

    try:
        payload = json.loads(raw or "{}")
    except ValueError as exc:
        print(f"the payload is not JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("the payload must be an object", file=sys.stderr)
        return 2

    try:
        verdict = judge(payload)
    except JudgeError as exc:
        print(f"Jev could not judge: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0 if verdict.get("met") else 1


if __name__ == "__main__":
    raise SystemExit(main())
