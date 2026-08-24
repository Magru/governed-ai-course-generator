# Model package

The seven specification pages one directory up are prose: they argue. These files
are the same facts in a form something other than a person can read — a diff, a
linter, a simulator.

Each file answers one question, names an owner, and says what event should make
someone change it. That is the whole convention.

| File | Answers | How it is maintained |
|---|---|---|
| [`system-definition.yaml`](system-definition.yaml) | What does the system promise? | by hand |
| [`functional-model.yaml`](functional-model.yaml) | What does the system do? | by hand |
| [`state-inventory.yaml`](state-inventory.yaml) | Where is state authoritative? | exported |
| [`transitions.yaml`](transitions.yaml) | What is permitted in each state? | exported |
| [`state-machine-revision.mmd`](state-machine-revision.mmd) · [`state-machine-node.mmd`](state-machine-node.mmd) | the same, as a picture — [rendered](diagrams.md) | exported |
| [`event-catalog.yaml`](event-catalog.yaml) | What do the events mean? | exported |
| [`failure-scenarios.yaml`](failure-scenarios.yaml) | How do we fail safely? | exported |

**Six of the framework's twenty artifacts.** The other fourteen are either partial
or absent, and the [system model page](../modeling.html) grades each one and says
which get built next.

## Regenerating

```
python3 export-model.py
```

Reads the tables in `../states.html`, `../transitions.html` and `../safety.html`
and rewrites everything marked *exported* above. It refuses to write anything if
a table has moved — the expected row counts are asserted first, so a silent
half-export is not possible. The two hand-maintained files it never touches.

## What the export found

Moving tables into files surfaced five things prose had been absorbing. None is
cosmetic; each is a question the specification does not currently answer.

1. **`BlockedFinal` exists in both machines** with different exits — terminal with
   no unblock path for a revision, terminal-to-the-machine for a node. Any tool
   reading state names unqualified will conflate them.
2. **Seven transition endpoints are not state names.** Six are expressions resolved
   at runtime — *the state that blocked*, *any state in the live lineage*, *the
   state after the operation*. Each needs a resolution rule before this package can
   drive a simulation. They are listed under `open_questions` in `transitions.yaml`.
3. **One node transition never says where the node goes.** `NodeRepair` on an
   exhausted retry budget records `course → BlockedRecoverable`: what happens to the
   *course*. The node's own target is unstated.
4. **`·` is overloaded** in the transition tables. In `ContentInProgress ·
   BlockedRecoverable` it means *either*; in `rev n+1 · ContentInProgress` it
   qualifies an object in a different revision. A reader infers which from context.
   A parser cannot.
5. **No event declares a payload.** The catalog gives every event a source and a
   target and leaves its fields to be inferred from the surrounding prose.

## Owners

Every file names `system architect` today, which is honest for a one-person
project and useless as governance. Real ownership splits at least three ways —
guardrail policy belongs to a compliance officer, the skills catalog to the
platform, pedagogical judgment to the editor — and the framework asks for the
owner precisely so that a stale artifact has someone to go stale on.
