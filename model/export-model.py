#!/usr/bin/env python3
"""Export the machine-readable half of the system model from the spec pages.

The specification pages are the source of truth for prose; these files are the
same facts in a form a linter, a simulator or a diff can read. Run from this
directory after editing any table in ../states.html, ../transitions.html or
../safety.html:

    python3 export-model.py

Endpoints in the transition tables are not always bare state names — some are
alternatives, some are expressions evaluated at runtime, some name an object in
a different machine. Rather than flatten that away, every endpoint is exported
verbatim as `*_raw` alongside a parsed form with an explicit `kind`, and the
ones that cannot be resolved are collected under `open_questions`.
"""
import datetime
import html
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SITE = HERE.parent
STAMP = datetime.date.today().isoformat()
IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


# ---------------------------------------------------------------- extraction

def _text(fragment):
    fragment = re.sub(r"<br\s*/?>", " / ", fragment)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def section(filename, anchor):
    page = (SITE / filename).read_text(encoding="utf-8")
    found = re.search(r'<section id="' + anchor + r'".*?</section>', page, re.S)
    if not found:
        sys.exit(f"FATAL: {filename} has no section #{anchor}")
    return found.group(0)


def table_rows(fragment):
    """Body rows only — headers and the phase captions that group them are dropped."""
    return [[_text(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
            for attrs, body in re.findall(r"<tr([^>]*)>(.*?)</tr>", fragment, re.S)
            if "<th" not in body and "phase" not in attrs]


# ------------------------------------------------------------------ emission

def q(value):
    """Always-valid double-quoted YAML scalar."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def header(artifact, question, updated_when, source, lines):
    lines += [f"artifact: {artifact}",
              f"question: {q(question)}",
              "owner: " + q("system architect"),
              f"updated_when: {q(updated_when)}",
              f"source: {q(source)}",
              f"generated: {q(STAMP)}",
              "generator: " + q("model/export-model.py"), ""]


# ------------------------------------------------------------------- parsing

def parse_endpoint(cell, known):
    """Classify a From/To cell. `states` is what a diagram may draw."""
    note = None
    bracketed = re.match(r"^(.*?)\s*\((.*)\)$", cell)
    base = cell
    if bracketed and bracketed.group(1).strip():
        base, note = bracketed.group(1).strip(), bracketed.group(2).strip()

    out = {"raw": cell, "note": note}
    if base in known:
        return {**out, "kind": "state", "states": [base]}

    parts = [p.strip() for p in base.split("·")]
    if len(parts) > 1 and all(p in known for p in parts):
        return {**out, "kind": "alternatives", "states": parts}
    if len(parts) > 1 and parts[-1] in known:
        return {**out, "kind": "other_object", "states": [parts[-1]],
                "qualifier": " · ".join(parts[:-1])}
    if "→" in base:
        return {**out, "kind": "cross_machine", "states": [], "expression": base}
    if base.lower().startswith(("any ", "the state")):
        return {**out, "kind": "expression", "states": [], "expression": base}
    return {**out, "kind": "unresolved", "states": []}


def emit_endpoint(prefix, parsed, lines, indent="    "):
    lines.append(f"{indent}{prefix}_raw: {q(parsed['raw'])}")
    lines.append(f"{indent}{prefix}_kind: {parsed['kind']}")
    if parsed["states"]:
        lines.append(f"{indent}{prefix}: [{', '.join(q(s) for s in parsed['states'])}]")
    for extra in ("qualifier", "expression", "note"):
        if parsed.get(extra):
            lines.append(f"{indent}{prefix}_{extra}: {q(parsed[extra])}")


# ----------------------------------------------------------------- artifacts

def write_state_inventory(revision, node):
    out = []
    header("state-inventory", "Where is state authoritative?",
           "a state is added, removed, or its exit conditions change",
           "states.html §2 (revision FSM) and §3 (node FSM)", out)
    out += ["# Both machines are held in the same state store; the store is authoritative",
            "# for every state below. `BlockedFinal` occurs in BOTH machines with different",
            "# exits — always qualify it by machine.", "",
            "machines:", "  revision:",
            f"    count: {len(revision)}",
            "    states:"]
    for name, meaning, editor in revision:
        out += [f"      - name: {q(name)}",
                f"        meaning: {q(meaning)}",
                f"        editor_can_do: {q(editor)}"]
    out += ["  node:", f"    count: {len(node)}", "    states:"]
    for name, meaning, exit_ in node:
        out += [f"      - name: {q(name)}",
                f"        meaning: {q(meaning)}",
                f"        exit: {q(exit_)}"]
    return "\n".join(out) + "\n"


def write_event_catalog(rows):
    out = []
    header("event-catalog", "What do the events mean?",
           "an event is added, renamed, or changes its source or target",
           "states.html §6", out)
    names = [n for row in rows for n in re.split(r"\s*/\s*", row[0])]
    out += [f"# {len(rows)} catalog entries covering {len(names)} named events. Entries that",
            "# carry several names group events that behave identically in the machine.",
            "# No payload is specified anywhere yet — see open_questions.", "",
            f"entry_count: {len(rows)}", f"event_count: {len(names)}", "events:"]
    for name, source, target in rows:
        split = [n.strip() for n in re.split(r"\s*/\s*", name)]
        out += [f"  - names: [{', '.join(q(n) for n in split)}]",
                f"    source: {q(source)}",
                f"    target: {q(target)}"]
    out += ["", "open_questions:",
            "  - " + q("No event carries a declared payload; consumers infer fields from prose.")]
    return "\n".join(out) + "\n"


def write_transitions(revision, node, known):
    out = []
    header("transitions", "What is permitted in each state?",
           "any row of the transition tables changes",
           "transitions.html §2 (revision) and §3 (node)", out)
    out += [f"# {len(revision)} revision transitions + {len(node)} node transitions.",
            "# Every endpoint is kept verbatim as *_raw; *_kind says how far it parsed.",
            "#   state         a single named state",
            "#   alternatives  several named states, any of which matches",
            "#   other_object  a state of a DIFFERENT object (a spawned revision)",
            "#   expression    resolved at runtime, not a name (e.g. the state that blocked)",
            "#   cross_machine an effect on the other machine rather than a target here", ""]
    unresolved = []
    for machine, rows in (("revision", revision), ("node", node)):
        out += [f"{machine}:"]
        for src, event, guard, layer, dst in rows:
            a, b = parse_endpoint(src, known), parse_endpoint(dst, known)
            out.append(f"  - event: {q(event)}")
            emit_endpoint("from", a, out, "    ")
            out.append(f"    guard: {q(guard)}")
            out.append(f"    layer: {q(layer)}")
            emit_endpoint("to", b, out, "    ")
            for side, p in (("from", a), ("to", b)):
                if p["kind"] in ("expression", "cross_machine", "unresolved"):
                    unresolved.append((machine, event, side, p["raw"], p["kind"]))
    out += ["", "open_questions:",
            "  note: " + q("The endpoints below are not state names. Each needs a resolution "
                           "rule before this file can drive a simulation."),
            "  unresolved_endpoints:"]
    for machine, event, side, raw, kind in unresolved:
        out += [f"    - machine: {machine}", f"      event: {q(event)}",
                f"      side: {side}", f"      raw: {q(raw)}", f"      kind: {kind}"]
    return "\n".join(out) + "\n", unresolved


def write_failures(situations, modes):
    out = []
    header("failure-scenarios", "How do we fail safely?",
           "a failure mode is discovered, or a situation changes its outcome",
           "states.html §5 (nine situations) and safety.html §10 (failure matrix)", out)
    out += [f"situations:  # {len(situations)}, each walked event by event"]
    for name, course, node, changes, editor in situations:
        out += [f"  - situation: {q(name)}", f"    course: {q(course)}",
                f"    node: {q(node)}", f"    also_changes: {q(changes)}",
                f"    editor_next: {q(editor)}"]
    out += ["", f"failure_modes:  # {len(modes)}"]
    for mode, looks_like, stopped_by, owner in modes:
        out += [f"  - mode: {q(mode)}", f"    looks_like: {q(looks_like)}",
                f"    stopped_by: {q(stopped_by)}", f"    owner: {q(owner)}"]
    return "\n".join(out) + "\n"


def write_mermaid(rows, known, title, terminal_hint):
    """One stateDiagram per machine. Unparseable endpoints become labelled pseudo-states
    rather than being dropped — a diagram that hides them would be a nicer lie."""
    lines = [f"---", f"title: {title}", "---", "stateDiagram-v2", "    direction LR"]
    pseudo, edges = {}, []

    def ids_for(parsed):
        if parsed["states"] and parsed["kind"] != "other_object":
            return parsed["states"]
        key = parsed["raw"]
        pseudo.setdefault(key, "X" + re.sub(r"[^A-Za-z0-9]", "", key)[:28] or f"X{len(pseudo)}")
        return [pseudo[key]]

    for src, event, guard, layer, dst in rows:
        a, b = parse_endpoint(src, known), parse_endpoint(dst, known)
        label = event if event != "(auto)" else "auto"
        for s in ids_for(a):
            for t in ids_for(b):
                edges.append(f"    {s} --> {t} : {label}")
    for raw, ident in sorted(pseudo.items(), key=lambda kv: kv[1]):
        lines.append(f'    state "{raw}" as {ident}')
    lines += ["", f"    [*] --> {terminal_hint}", ""] + edges
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- main

def main():
    rev_states = table_rows(section("states.html", "s2"))
    node_states = table_rows(section("states.html", "s3"))
    events = table_rows(section("states.html", "s6"))
    situations = table_rows(section("states.html", "s5"))
    rev_tr = table_rows(section("transitions.html", "s2"))
    node_tr = table_rows(section("transitions.html", "s3"))
    modes = table_rows(section("safety.html", "s10"))

    expect = [("revision states", rev_states, 21), ("node states", node_states, 11),
              ("events", events, 23), ("situations", situations, 9),
              ("revision transitions", rev_tr, 55), ("node transitions", node_tr, 19),
              ("failure modes", modes, 14)]
    bad = [f"{n}: got {len(r)}, expected {e}" for n, r, e in expect if len(r) != e]
    if bad:
        sys.exit("NOTHING WRITTEN — the pages moved:\n  " + "\n  ".join(bad))

    known = {r[0] for r in rev_states} | {r[0] for r in node_states}
    transitions, unresolved = write_transitions(rev_tr, node_tr, known)
    files = {
        "state-inventory.yaml": write_state_inventory(rev_states, node_states),
        "event-catalog.yaml": write_event_catalog(events),
        "transitions.yaml": transitions,
        "failure-scenarios.yaml": write_failures(situations, modes),
        "state-machine-revision.mmd": write_mermaid(rev_tr, known, "Revision state machine", "AwaitingBrief"),
        "state-machine-node.mmd": write_mermaid(node_tr, known, "Node state machine", "Planned"),
    }
    # GitHub shows .mmd as plain text but renders fenced mermaid in Markdown, so the
    # same two diagrams are emitted again here — generated, never hand-copied.
    files["diagrams.md"] = (
        "# State machines\n\n"
        "Generated from `transitions.yaml` by `export-model.py` on " + STAMP + ".\n"
        "Do not edit: change `../transitions.html` and re-run the exporter.\n\n"
        "## Revision machine\n\n```mermaid\n"
        + files["state-machine-revision.mmd"] + "```\n\n"
        "## Node machine\n\n```mermaid\n"
        + files["state-machine-node.mmd"] + "```\n")

    for name, body in files.items():
        (HERE / name).write_text(body, encoding="utf-8")
        print(f"  ✓ {name}  ({len(body.splitlines())} lines)")
    print(f"\n{len(unresolved)} endpoints could not be resolved to a state name "
          f"— listed under open_questions in transitions.yaml")


if __name__ == "__main__":
    main()
