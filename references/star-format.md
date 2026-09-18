# Star format

A star is one JSON object. Write it with the tool (`set --from-json`), never by hand, so the
refusal rules run before a run does.

## Fields

| Field | Required | What it is |
|---|---|---|
| `goal` | yes | One sentence, the finished state seen from the outside. Under 300 characters. No mood words. |
| `for_whom` | yes | Who it is finished for. A stranger, a buyer, a client, the owner. |
| `requirements` | yes | The states that must be true for the goal to hold. One to twelve. |
| `checks` | yes | Object keyed by the exact requirement text: how you would see that it is true. |
| `out_of_scope` | yes | At least one thing this explicitly is not. |
| `stop_rule` | yes | When the run stops and what it hands back. |
| `first_action` | yes | The first thing the run should do. |
| `ground_truth` | no, strongly advised | Literal facts the run must never re-derive: repo, branch, remote, host, ports, where credentials live and the rule about them, invariants corrected before. |
| `gates` | no | Shell commands that exit 0 when a machine-checkable part of the goal is true. |

Any other field is refused. An unknown field is a note to yourself that nobody reads.

## Refusal rules

The tool refuses a star, exits 2, and lists every problem it found:

- `goal` missing, empty, over 300 characters, or containing a mood word.
- `for_whom` missing.
- No requirements, or more than twelve.
- A requirement over 200 characters, or containing a mood word.
- A requirement with no entry in `checks`.
- A check that is empty, shorter than three words, or identical to the requirement it is meant to
  verify.
- A `checks` key that does not match a requirement exactly. Copy the requirement text verbatim.
- `out_of_scope` empty.
- `stop_rule` missing. `first_action` missing.
- `gates` that is not a list.
- Any unknown field.

## Mood words

Refused in `goal` and in any requirement, because nothing observable follows from them:

```
polished, seamless, robust, world-class, production-ready, better ux, works well,
clean up, more professional, optimized, best practices, modern, scalable
```

When a mood shows up, ask what the owner would point at instead, and put that answer in the star.

## Notes, not refusals

These print as `note:` lines and still save, because a human can judge whether they matter:

- A check that names no observable action. The tool looks for verbs like run, open, read, compare,
  check, test, print, log, curl, grep, diff, measure, count, poll, or a backticked command. A check
  that reads like a feeling is worth rewriting.
- A check that says the requirement twice in different words.

## Where the files go

`$NORTH_STAR_HOME`, default `~/.hermes/north-star`:

```
stars/<name>.json     the stars
state/<name>.md       the evidence each run leaves behind
```

Both are plain files. Nothing to migrate, nothing to export.

## Example

See `templates/star.example.json` for a star that passes, and `SKILL.md` for the questions that
produce one.
