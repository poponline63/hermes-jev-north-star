# hermes-north-star

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) skill that turns an intention into
a finish line an agent can be held to, then generates the prompt that starts the run.

Long autonomous runs fail in one of two ways: they stop early and call it done, or they never
stop. Both come from the same missing thing, a written finish line with states someone can point
at. This skill interviews the owner until that exists, refuses it if it cannot be judged, and
hands back three artifacts: the star, the generated run prompt, and the gate command that decides
whether the work is actually finished.

Everything runs offline. No dependencies, no API key, no model required. The optional judge is
any command you supply yourself.

Not an official Nous Research project.

## Install

```bash
hermes skills install https://raw.githubusercontent.com/poponline63/hermes-north-star/main/SKILL.md
```

A SKILL.md URL is what Hermes installs from. `hermes skills inspect <same url>` previews it first.
That install copies the skill document, `references/`, and `templates/`; it does not copy
`scripts/`, so clone the repo once to have the tool on disk:

```bash
git clone https://github.com/poponline63/hermes-north-star ~/hermes-north-star
python3 ~/hermes-north-star/scripts/north_star.py --help
```

Then in a chat session:

```
/hermes-north-star the public downloads page for my CLI tool is finished
```

Any agent that can run a shell command can use it without Hermes at all: the skill is one markdown
file plus one stdlib Python script.

## Quick start

Write a star as JSON:

```json
{
  "goal": "a stranger can install the CLI, run it against their own data, and get a correct report without asking anyone for help",
  "for_whom": "someone who found the repo today and has never spoken to the maintainer",
  "requirements": [
    "the documented install command works on a clean machine",
    "the example in the README runs against the shipped sample data and prints a report"
  ],
  "checks": {
    "the documented install command works on a clean machine": "run the install line from the README in a fresh container and paste the output",
    "the example in the README runs against the shipped sample data and prints a report": "copy-paste the README example verbatim and compare its output to the sample report in docs/"
  },
  "out_of_scope": ["packaging for other operating systems", "a hosted version"],
  "stop_rule": "stop when both are demonstrably true; hand back before changing anything a user's data depends on",
  "first_action": "run the README install line in a container and record exactly what it prints"
}
```

Save it and get the run prompt:

```bash
$ python3 scripts/north_star.py set downloads-page --from-json star.json
north star 'downloads-page' saved: ~/.hermes/north-star/stars/downloads-page.json
2 requirements, 2 with a stated verification.

prompt for the run:
  python3 scripts/north_star.py prompt downloads-page

$ python3 scripts/north_star.py prompt downloads-page
GOAL
a stranger can install the CLI, run it against their own data, and get a correct report without
asking anyone for help. Finished for: someone who found the repo today and has never spoken to
the maintainer.

GROUND TRUTH - do not re-derive any of this
- (fill this in: repo + branch + remote, host + access + ports, where credentials live ...)

WHAT MUST BE TRUE, AND HOW EACH ONE IS SEEN
1. the documented install command works on a clean machine
   Done when: run the install line from the README in a fresh container and paste the output
2. the example in the README runs against the shipped sample data and prints a report
   Done when: copy-paste the README example verbatim and compare its output to the sample report in docs/
...
```

Paste that prompt into a fresh run. The run appends what it actually finds to an evidence file as
it works, and the gate judges that file:

```bash
$ python3 scripts/north_star.py evidence downloads-page --add "ran the README install line in a fresh container: exit 0, 12 packages"
$ python3 scripts/north_star.py gate downloads-page
Goal not met: a stranger can install the CLI, ...
No judge is configured (--judge), so nothing here ranks the requirements. Take the first one that is not proven yet.
Start with: the documented install command works on a clean machine
Done when: run the install line from the README in a fresh container and paste the output
$ echo $?
1
```

Exit 0 means met. Exit 1 means keep going, and stdout is the next step. Exit 2 means the star is
missing or not drivable, so nothing was judged.

## What the tool refuses

The refusals are the point. A star that cannot be driven is worse than no star, because a run
will happily satisfy the wrong sentence.

```bash
$ python3 scripts/north_star.py set app --from-json bad.json
refused: this star cannot drive a run (9 problem(s)):
- goal: 'polished' is a mood, not a state. Say what would be true instead.
- for_whom: missing. Who is this finished for?
- requirement 'better UX...': 'better ux' cannot be pointed at.
- checks: the requirement is stated twice, nothing is verified -> better UX
- checks: no way to see that this is true -> clean up the code
- out_of_scope: empty. The boundary is what stops a run wandering.
- stop_rule: missing. When does the run stop and hand back?
- first_action: missing. What is the first thing it should do?
```

It also refuses unknown fields, over-long requirements, and more than twelve of them. Two softer
cases only produce a note: a check that names no observable action, and a check that is too short
to verify anything.

## The gate

Order of business, cheapest first:

1. **Deterministic gates** (`gates` in the star): shell commands that exit 0 when a
   machine-checkable part of the goal is true. A failure short-circuits everything and its own
   output becomes the next step.
2. **The evidence file** (`~/.hermes/north-star/state/<name>.md`). Empty, and the gate refuses to
   judge at all rather than guessing.
3. **The judge**, if you pass one. Any command:

```bash
python3 scripts/north_star.py gate downloads-page --judge "python3 my_judge.py"
```

```python
# my_judge.py - reads the star + state as JSON on stdin
import json, sys
data = json.load(sys.stdin)
print(json.dumps({"met": False, "weakest": data["requirements"][0]}))
```

The judge prints `{"met": true|false, "weakest": "<requirement, optional>"}`, or prints nothing
at all and lets its exit code decide (0 = met). A judge that prints text without a readable
verdict is treated as unreachable: a broken answer must never read as agreement, and a gate that
cannot reach its judge never passes silently.

The judge runs through a shell, so quote paths that contain spaces. If it cannot be launched at
all, the gate says so and returns not-met rather than passing.

In Hermes, a failing gate short-circuits the loop's own judge, so the run continues on a concrete
next step rather than on a model's opinion about its own progress:

```
/goal gate add python3 <skill>/scripts/north_star.py gate downloads-page
```

## Layout

```
SKILL.md                      the skill itself
scripts/north_star.py         the CLI: set, check, prompt, evidence, gate
scripts/smoke_test.py         every claim above, asserted
templates/star.example.json   a star that passes, to start from
references/star-format.md     field reference and the refusal rules
```

Run the tests:

```bash
python3 scripts/smoke_test.py
```

## Where stars live

`$NORTH_STAR_HOME`, defaulting to `~/.hermes/north-star`:

```
stars/<name>.json     the stars
state/<name>.md       the evidence each run leaves behind
```

Plain files. Readable, diffable, and yours. No database, nothing to migrate.

## License

MIT. See [LICENSE](LICENSE).
