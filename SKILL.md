---
name: hermes-jev-north-star
description: Use when a project needs a north star, a finish line, or a definition of done. Interviews the owner one question at a time, saves a star the run can be judged against, generates the goal prompt to hand the run, and gives Jev the fuzzy requirements to judge.
version: 1.1.0
metadata:
  hermes:
    tags: [planning, goals, autonomy, verification, definition-of-done]
    category: development
---

# North star

Turn an intention into a finish line an agent can actually be held to: a goal, the states that
must be true for it to be met, and a way to see each one. Then generate the prompt that starts
the run, from the same file the gate judges.

**A run of this skill is not finished when the star is saved.** It ends with three deliverables,
in this order:

1. **The star**, saved and passing `check`.
2. **The goal prompt**, printed by `prompt` in full, in one fenced block, so the owner can copy
   it and paste it back to start the long run.
3. **How to judge it**, the `gate` command and what its exit codes mean.

The prompt is generated, never hand-written, because it has to say the same words the gate
judges. If the star is edited, the prompt is regenerated.

A star is not a theme. "Make it polished" cannot be judged, so the loop that reads it cannot pick
a next action and the gate can never honestly say done. The whole job here is to turn an
intention into states someone can point at.

## Getting the tool

`north_star.py` runs every command below, and it has to exist on disk.

- **From a clone:** run `python3 scripts/north_star.py ...` at the repo root.
- **From an installed skill:** the hub copies this document, `references/`, and `templates/` when
  you install from a SKILL.md URL, and it does not copy `scripts/`. Clone the repo once so the
  tool is there:

```bash
git clone https://github.com/poponline63/hermes-jev-north-star ~/hermes-jev-north-star
python3 ~/hermes-jev-north-star/scripts/north_star.py --help
```

Everywhere below, `<tool>` means whichever path is real for your install. The tests are
`scripts/smoke_test.py` (77 checks, no key, no network), the judge is `scripts/jev_judge.py`, the
starting template is `templates/star.example.json`, and the reference is
`references/star-format.md`. Source and issues:
<https://github.com/poponline63/hermes-jev-north-star>.

## Commands

```bash
python3 <tool> set <name> --from-json <file|->   # validated; exits 2 and lists the problems
python3 <tool> check <name>                      # re-check a saved star
python3 <tool> check --all                       # re-check all of them
python3 <tool> list | show <name>
python3 <tool> prompt <name>                     # the paste-ready run prompt
python3 <tool> evidence <name> --add "one line"  # what the run learned
python3 <tool> gate <name>                       # exit 0 = met, 1 = keep going
python3 <tool> rm <name>
```

No dependencies, no network, no model required. `--home` (or `$NORTH_STAR_HOME`) decides where
stars live; the default is `~/.hermes/north-star`.

## The star

One JSON object, saved through the tool, never by hand:

```json
{
  "goal": "one sentence: the finished state, seen from the outside",
  "for_whom": "who it is finished for",
  "requirements": ["a state that must be true", "another state"],
  "checks": {"<requirement, copied exactly>": "how you would see that it is true"},
  "out_of_scope": ["something this is explicitly not"],
  "stop_rule": "when the run stops and what it hands back",
  "first_action": "the first thing the run should do",
  "ground_truth": ["repo + branch + remote", "host + access + ports",
                   "where credentials live, and the rule about them",
                   "an invariant the owner has had to correct before"],
  "gates": ["a command that exits 0 when a machine-checkable part is true"]
}
```

`ground_truth` is what the run must never re-derive: literal values only, no prose. It is
optional in the schema and the run goes badly without it, so ask for it. `gates` is optional too
and is the cheapest part of the gate: deterministic commands that run before anything judgmental.
See `references/star-format.md` for the full field reference and every refusal rule.

The name is a slug: the project, lowercase.

## How to ask

- One question at a time. Give two to four concrete options. Never a wall of questions in prose.
- Look before you ask. If the repo, its README, or a command's output already answers it, find it
  and state what you found instead of asking.
- Ask only what does not hinge on a question not yet answered.
- Cap it at eight questions. A star is a finish line, not a project plan.

### The questions that matter, in order

1. Who is this finished for? A stranger, a buyer, a client, you. This reframes every other answer.
2. What is true the day it is done? One sentence the owner would say out loud.
3. What must be true for that sentence to hold? Push for three to six, each a state.
4. For each one: how would we see it is true? A command, a page, a test, a log line, a purchase.
   This is the question that makes the star drivable. Never skip it.
5. What is this explicitly not? The boundary is what stops a run wandering.
6. When should the run stop and hand back?
7. What must the run never re-derive? Repo, branch, remote, host, ports, where credentials live
   and the rule about them, invariants corrected before. Literal values only.
8. What is the first thing it should do?

## Rules that keep it honest

- A requirement with no way to check it is not a requirement. Rewrite it until it has one, or
  drop it. The tool refuses a star that breaks this.
- Refuse moods: "polished", "better UX", "works well", "clean up", "robust", "production-ready".
  Ask what the owner would point at instead, and use that answer.
- The owner's words become the requirement text. Do not paraphrase intent into model phrasing.
- A requirement that needs a payment, a publish, or an outbound message goes in the star as a
  hand-back, never as something the run may do alone.
- Read the finished star back in the owner's own words and get a yes before saving it.
- If a model is available to rank candidate finish lines, use it for that and nothing else. It
  must never write the star: this is the owner's intent, not a model's guess.

## The gate

`gate` reads the run's evidence file (`~/.hermes/north-star/state/<name>.md`) and answers with an
exit code:

- **0** the goal is met.
- **1** keep going. stdout is the next step, naming the weakest requirement and how it is seen.
- **2** the star is missing or not drivable, so nothing was judged.

Its order matters: deterministic `gates` first (a failure short-circuits and its output becomes
the next step), then the state, then a judge if one is configured.

Two things it refuses to do:

- **Judge nothing.** No state passed and an empty evidence file means there is nothing to judge,
  so it says so instead of guessing.
- **Claim done without a verdict.** With no judge it says plainly that nothing ranks the
  requirements, and it never returns 0 on the strength of an empty or unreadable answer.

A judge is any command. It gets the star and the state as JSON on stdin and prints
`{"met": true|false, "weakest": "<requirement>"}`, or prints nothing and lets its exit code
decide. Point `--judge` at a script, a model call, or another agent. A judge that prints text
without a readable verdict counts as unreachable, because a broken answer must never read as
agreement.

The judge runs through a shell, so quote paths that contain spaces:
`--judge "\"/path with spaces/python\" judge.py"`. If the judge cannot be launched, the gate says
so and returns not-met rather than passing.

### Jev is the default judge

When a `TYPESAFE_API_KEY` is configured (`~/.hermes/.env` counts), the gate uses the bundled Jev
judge without being asked, because the fuzzy requirement is exactly the part a script cannot read:

```bash
python3 <tool> gate <name>              # Jev when a key exists, deterministic when it does not
python3 <tool> gate <name> --judge jev  # insist on Jev, fail closed if it cannot answer
python3 <tool> gate <name> --no-judge   # no model at all, and it says so
```

One Jev call (`scripts/jev_judge.py`) asks three typed questions about the run's evidence: is every
requirement met (`noul`), how far along is this on four levels (`score`), and which requirement is
furthest from being met (`choice`). The gate prints what it got back, never just a boolean:

```
Judge: done 0.02 (needs 0.6), progress 1.05, confidence 0.96, jev-1.13.0, 921+176 tokens
Weakest requirement: a play-driven buy fills in a funded account
```

Two honest limits, both learned by measuring it on a real project:

- Its numbers move between calls on the same state, and on an empty state it once answered "nothing
  material, every requirement looks met" beside a done probability of 0.14. The empty-state refusal
  exists because of that, and the deterministic checks are the load-bearing part of the gate.
- Each gate run with Jev costs one API call. `--no-judge` exists so a run can poll the gate
  cheaply, and the environment knobs (`JEV_THRESHOLD`, `JEV_MODEL`, `JEV_TIMEOUT`,
  `TYPESAFE_BASE_URL`) are documented at the top of `scripts/jev_judge.py`.

In Hermes, the core goal loop runs a gate as a static shell command with no stdin, which is why
the evidence lives in a file the running turn keeps updating:

```
/goal gate add python3 <tool> gate <name>
```

## Pitfalls

- **Trusting the judge with the parts a script can check.** Deterministic `gates` run first for a
  reason: a shell command cannot be talked out of its answer.

- **The star drifts from the prompt.** Never hand-edit a generated prompt. Edit the star and run
  `prompt` again.
- **A check that restates the requirement.** "Works when it works" verifies nothing; the tool
  refuses the exact-copy case and flags checks that name no observable action.
- **Too many requirements.** Past twelve this is a plan. A star the run cannot finish is a star
  that never gates anything.
- **An empty evidence file at the end of a long run.** The gate then has nothing to judge. Tell
  the run to append as it goes, one line per real result, not at the end from memory.
- **Trusting an accepted request as a result.** A queued job is not a fill, an opened ticket is
  not a fix. Say what the system says, not what was asked for.

## Verification

- `check <name>` exits 0 and prints `drivable`.
- `prompt <name>` prints a prompt containing `GOAL`, `WHAT MUST BE TRUE`, `STOP`, and the gate
  command.
- `gate <name>` exits 1 with an empty evidence file and names the weakest requirement once the
  file has a line in it.
- `gate <name> --judge jev` with no key exits 1 and says the judge could not be reached, instead of
  quietly returning a deterministic verdict.
- `scripts/smoke_test.py` runs the whole suite against a stand-in endpoint, so it needs no key and
  makes no network calls.
- `templates/star.example.json` passes `check --file`.
