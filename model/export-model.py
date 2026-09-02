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
            "  cross_machine_leak:",
            "    status: resolved",
            "    was: " + q("Two node transitions targeted ErrorRecovery, a revision state the "
                            "node machine neither declared nor left, so a node that timed out "
                            "had no exit at all."),
            "    now: " + q("The node machine declares NodeRecovery and leaves it three ways: "
                            "the write landed, a retry inside budget, or a person clearing the "
                            "cause once the budget is spent."),
            "    found_by: " + q("exporting the tables into files; a month of prose and four "
                                 "rounds of review never surfaced it"),
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


# ----------------------------------------------------------------------- lint

def guard_count():
    """Names in the guard glossary, counting ·-paired entries separately."""
    block = section("transitions.html", "s4")
    return sum(len(re.split(r'\s*·\s*', _text(d)))
               for d in re.findall(r'<dt[^>]*>(.*?)</dt>', block, re.S))


def lint(rev_states, node_states, events, rev_tr, node_tr):
    """state-inventory.yaml and event-catalog.yaml are maintained by hand, because
    the facts they carry — variable types, owners, recovery, command-vs-event — are
    nowhere in the HTML. They are checked against the tables instead of generated,
    so a name added to a page and forgotten in the model is caught here."""
    problems = []

    inv = (HERE / "state-inventory.yaml").read_text(encoding="utf-8")
    for name, _, _ in rev_states + node_states:
        if f'"{name}"' not in inv:
            problems.append(f"state-inventory.yaml is missing state {name}")

    # A machine may only name its own states. The union check this replaced was
    # blind to a node transition targeting a revision state — which is how a node
    # came to reach ErrorRecovery, a state the node machine does not declare and
    # does not leave.
    problems += cross_machine_leaks(rev_states, node_states)

    cat = (HERE / "event-catalog.yaml").read_text(encoding="utf-8")
    for row in events:
        for name in re.split(r"\s*/\s*", row[0]):
            if f'"{name.strip()}"' not in cat:
                problems.append(f"event-catalog.yaml is missing event {name.strip()}")

    inv_file = (HERE / "invariants.yaml").read_text(encoding="utf-8")
    for formula in spec_invariants():
        if formula not in inv_file:
            problems.append(f"invariants.yaml is missing {formula}")

    problems += figure_drift()
    problems += prose_counts({
        "rev_states": len(rev_states), "node_states": len(node_states),
        "rev_tr": len(rev_tr), "node_tr": len(node_tr),
        "event_rows": len(events),
        "event_names": sum(len(re.split(r'\s*/\s*', r[0])) for r in events),
        "guards": guard_count(),
    })

    if problems:
        sys.exit("NOTHING WRITTEN — the hand-maintained files have fallen behind:\n  "
                 + "\n  ".join(problems))
    print(f"  · lint ok: {len(rev_states) + len(node_states)} states and "
          f"{sum(len(re.split(chr(47), r[0])) for r in events)} event names accounted for")


# The one leak that exists today, carried explicitly so a NEW one fails the run.
# Not a licence: it is a defect, recorded in transitions.yaml under open_questions.
ACCEPTED_LEAKS = {}  # the one that existed was fixed by giving the node its own recovery


def cross_machine_leaks(rev_states, node_states):
    """Every endpoint a machine names must be one of that machine's own states."""
    own = {"revision": {r[0] for r in rev_states}, "node": {r[0] for r in node_states}}
    out = []
    for machine, anchor in (("revision", "s2"), ("node", "s3")):
        for src, _, _, _, dst in table_rows(section("transitions.html", anchor)):
            for cell in (src, dst):
                parsed = parse_endpoint(cell, own["revision"] | own["node"])
                for st in parsed["states"]:
                    if st not in own[machine] and (machine, st) not in ACCEPTED_LEAKS:
                        out.append(f"{machine} machine reaches {st}, which it does not declare")
    return sorted(set(out))


KNOWN_NON_STATES = {"GuardrailVerdict", "NodeGenerated", "NodeEdited", "NodeApproved",
                    "NodeRejected", "OutlineGenerated", "LivePointerMoved",
                    "LearnersNotified", "CheckFailed"}


def trace_schema_lint(known, events):
    """trace-schema.yaml names states and events; both belong to other files.

    The schema is authored, not generated — it says what a run must carry so a
    property can be decided about it. Authored means it can drift, and the way
    it drifts is by naming a state that has since been renamed. Two greps stop
    that: every capitalised state name it mentions must exist in the inventory,
    and every event it calls side-effecting must exist in the catalog.
    """
    path = HERE / "trace-schema.yaml"
    if not path.exists():
        sys.exit("FATAL: trace-schema.yaml is missing — the invariant checks have no declared shape")
    text = path.read_text(encoding="utf-8")
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))

    # State names appear inside prose; take every CamelCase token and keep the
    # ones that look like state names rather than ordinary capitalised words.
    tokens = set(re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", body))
    unknown = sorted(t for t in tokens if t not in known and t not in KNOWN_NON_STATES)
    if unknown:
        sys.exit("trace-schema.yaml names " + ", ".join(unknown) +
                 " — not a state in states.html. Rename it there or fix the schema.")

    declared_events = set(re.findall(r'"([A-Z][A-Za-z]+)"', body))
    catalog = {n.split("(")[0].strip()
               for r in events for n in re.split(r"\s*[·/]\s*", _text(r[0]))}
    side = re.search(r"events: \[(.*?)\]", body, re.S)
    side_names = set(re.findall(r'"([^"]+)"', side.group(1))) if side else set()
    stray = sorted(side_names - catalog)
    if stray:
        sys.exit("trace-schema.yaml calls " + ", ".join(stray) +
                 " side-effecting, and states.html §6 has no such event")
    return len(side_names)


def spec_invariants():
    """The temporal formulas, lifted verbatim from the specification."""
    block = re.search(r'<div class="formula"[^>]*>(.*?)</div>',
                      section("states.html", "s8"), re.S)
    if not block:
        sys.exit("FATAL: states.html §8 has no formula block")
    out = []
    for line in re.split(r"<br\s*/?>|\n", block.group(1)):
        text = _text(line).split("←")[0].strip()
        if re.search(r"\b[GFXO]\s*\(", text):
            out.append(text)
    return out


# Figures that appear on more than one surface. Cross-view consistency is the
# thing this framework is loudest about, and the numbers drifted twice before
# this check existed: a budget was recomputed and its copies were not.
FIGURE_SOURCES = {
    "mean_node_s": r"mean_node_s:\s*([\d.]+)",
    "with_headroom": r"with_headroom:\s*([\d.]+)",
}


def figure_drift():
    """One file owns a number. latency-budget.yaml owns the timing figures; no
    other file may restate them, because restating is how they drifted twice."""
    budget = (HERE / "latency-budget.yaml").read_text(encoding="utf-8")
    canon = {}
    for key, pattern in FIGURE_SOURCES.items():
        found = re.search(pattern, budget)
        if not found:
            return [f"latency-budget.yaml no longer states {key}"]
        canon[key] = float(found.group(1))

    out = []
    banned = ("node_generation_s", "editors_per_model_worker", "mean_node_s", "with_headroom")
    for name in ("system-definition.yaml", "assumptions.yaml", "invariants.yaml"):
        text = (HERE / name).read_text(encoding="utf-8")
        for key in banned:
            if f"{key}:" in text:
                out.append(f"{name} restates {key}; latency-budget.yaml owns it")

    # Prose surfaces may round, but not contradict.
    for name, path in (("README.md", HERE / "README.md"),
                       ("modeling.html", SITE / "modeling.html")):
        text = path.read_text(encoding="utf-8")
        for n in re.findall(r"(?<![\d.])(\d{1,2})\s+s\b(?=[^<]{0,40}(?:produce|node))", text):
            if abs(int(n) - canon["mean_node_s"]) > 1:
                out.append(f"{name} says {n} s per node; the budget says {canon['mean_node_s']}")
        # Prose must use the budget's own recommendation word, not merely a
        # number near it — otherwise two surfaces round differently and disagree.
        rec = re.search(r"recommendation: \"one model worker per (\w+) editors",
                        budget)
        if rec:
            for word in ("six", "seven", "eight", "nine", "ten", "eleven", "twelve"):
                if word == rec.group(1):
                    continue
                if re.search(rf"\b(?:about |roughly )?{word} (?:concurrent )?editors\b", text):
                    out.append(f"{name} says {word} editors; the budget recommends "
                               f"{rec.group(1)}")
    return sorted(set(out))


# Prose carries counts that no table check reads, and three audit rounds in a row
# found a figure corrected in one place and left standing in another. Each claim
# below names where a number appears in prose and which real count it must equal.
# A claim whose pattern stops matching is itself a failure: the sentence moved and
# nobody re-pointed the check at it.
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
         7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
         14: "fourteen", 15: "fifteen", 19: "nineteen", 21: "twenty-one",
         22: "twenty-two", 23: "twenty-three", 24: "twenty-four", 25: "twenty-five",
         32: "thirty-two", 37: "thirty-seven", 38: "thirty-eight",
         55: "fifty-five", 56: "fifty-six"}

PROSE_CLAIMS = [
    ("transitions.html", r"Guards: <b>(\d+)</b>", "guards"),
    ("transitions.html", r"Revision transitions: <b>(\d+)</b>", "rev_tr"),
    ("transitions.html", r"Node transitions: <b>(\d+)</b>", "node_tr"),
    ("transitions.html", r"the tables above need ([a-z-]+) more to be complete", "guards_minus_13"),
    ("transitions.html", r"All ([a-z-]+), with their owner", "guards"),
    ("states.html", r"lists all ([a-z-]+), each with what it produces", "guards"),
    ("states.html", r"The same ([a-z-]+) states", "node_states"),
    ("index.html", r"with all ([a-z-]+) guards written out", "guards"),
    ("specification.html", r"with all ([a-z-]+) guards written out", "guards"),
    ("index.html", r"<b>(\d+) \+ (\d+)</b>", "states_pair"),
    ("modeling.html", r"<b>(\d+) \+ (\d+)</b> states", "states_pair"),
    ("modeling.html", r"<b>(\d+) \+ (\d+)</b> transitions", "tr_pair"),
    ("modeling.html", r"transitions behind (\d+) guards", "guards"),
    ("modeling.html", r"<b>(\d+)</b> named events", "event_names"),
    ("modeling.html", r"Seven commands separated from ([a-z-]+) events", "event_names_minus_7"),
    ("README.md", r"(\d+) revision states, (\d+) node states", "states_pair"),
    ("README.md", r"with all (\d+) guards", "guards"),
]


def prose_counts(counts):
    """Every number written in prose must equal the number in the tables."""
    out = []
    want = dict(counts)
    want["guards_minus_13"] = counts["guards"] - 13
    want["event_names_minus_7"] = counts["event_names"] - 7

    for name, pattern, key in PROSE_CLAIMS:
        text = (SITE / name).read_text(encoding="utf-8")
        found = re.search(pattern, text)
        if not found:
            out.append(f"{name}: the sentence behind claim <{key}> is gone — "
                       f"re-point the check at where it moved")
            continue
        got = [g for g in found.groups() if g]
        if key == "states_pair":
            exp = [counts["rev_states"], counts["node_states"]]
        elif key == "tr_pair":
            exp = [counts["rev_tr"], counts["node_tr"]]
        elif key == "events_pair":
            exp = [counts["event_rows"], counts["event_names"]]
        else:
            exp = [want[key]]
        for g, e in zip(got, exp):
            n = int(g) if g.isdigit() else {v: k for k, v in WORDS.items()}.get(g)
            if n != e:
                out.append(f"{name}: prose says {g!r} where the tables say {e} ({key})")
    return out


def package_tally():
    """modeling.html grades itself in three places; all three must agree.

    Each artifact row carries a present/partial/absent mark, each group header
    restates the totals, and the closing paragraph restates them again. The
    marks are the fact; the other two are copies, and this round the copies were
    wrong the moment two artifacts changed grade. Counting them here is cheaper
    than remembering to.
    """
    text = (SITE / "modeling.html").read_text(encoding="utf-8")
    marks = {"have": "present", "part": "partial", "none": "absent"}
    out = []

    groups = re.split(r'<div class="grp">', text)[1:]
    total = {"present": 0, "partial": 0, "absent": 0}
    for chunk in groups:
        tally = re.search(r'<span class="tally">(.*?)</span>', chunk)
        if not tally:
            continue
        got = {"present": 0, "partial": 0, "absent": 0}
        # Only the artifact rows count. The same marks appear elsewhere on the
        # page, against the framework's six parts, and those are a different
        # tally that this one was briefly conflated with.
        for row in re.findall(r"<tr>(?:(?!</tr>).)*?</tr>", chunk, re.S):
            if 'class="art"' not in row:
                continue
            cls = re.search(r'<span class="cov (have|part|none)">', row)
            if cls:
                got[marks[cls.group(1)]] += 1
        for k in got:
            total[k] += got[k]
        name = re.search(r"<h3>(.*?)</h3>", chunk)
        said = dict((m[1], int(m[0])) for m in
                    re.findall(r"(\d+) (present|partial|absent)", tally.group(1)))
        for grade, n in got.items():
            if said.get(grade, 0) != n:
                out.append(f"modeling.html: {_text(name.group(1))} counts {n} "
                           f"{grade} and its header says {said.get(grade, 0)}")

    closing = re.search(r"(\w+) present, (\w+) partial, (\w+) absent", text)
    if not closing:
        out.append("modeling.html: the sentence stating the package tally is gone")
    else:
        for word, grade in zip(closing.groups(), ("present", "partial", "absent")):
            n = (int(word) if word.isdigit()
                 else {v: k for k, v in WORDS.items()}.get(word.lower()))
            if n != total[grade]:
                out.append(f"modeling.html: the tally sentence says {word} "
                           f"{grade} where the rows count {total[grade]}")
    return out


def write_guards():
    """The glossary is the only place a guard is attributed to an owner.

    The transition table's Layer column lists everything that runs at that
    transition, which is a different fact and was briefly mistaken for this one.
    Without this file a reader — or a test — has no machine-readable answer to
    "who refuses this", and phase-03's guard registry has nothing to build on.
    """
    block = section("transitions.html", "s4")
    out = []
    header("guards", "Which layer owns each guard, and what does it hand back when it refuses?",
           "a guard is added, renamed, or changes owner",
           "transitions.html §4 — the guard glossary, one entry per name", out)
    out += ["# The transition tables' Layer column lists everything that runs at a",
            "# transition. This file answers the different question of who owns a",
            "# particular guard — the two were briefly mistaken for each other.", ""]
    body_lines = []
    count = 0
    for dt, dd in re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd>(.*?)</dd>", block, re.S):
        owner = re.search(r'<span class="owner">(.*?)</span>', dd)
        body = _text(re.sub(r'<span class="owner">.*?</span>', "", dd, flags=re.S))
        refusal = ""
        for marker in ("Refuses with", "Refuses by", "Refuse with", "refuses with"):
            if marker in body:
                refusal = body.split(marker, 1)[1].strip().rstrip(".")
                break
        for name in re.split(r"\s*·\s*", _text(dt)):
            count += 1
            body_lines.append(f"  - name: {q(name)}")
            body_lines.append(f"    owner: {q(_text(owner.group(1)) if owner else 'unstated')}")
            if refusal:
                body_lines.append(f"    refuses_with: {q(refusal[:200])}")
    out.append(f"count: {count}")
    out.append("guards:")
    out += body_lines
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- main

def main():
    rev_states = table_rows(section("states.html", "s2"))
    node_states = table_rows(section("states.html", "s3"))
    events = table_rows(section("states.html", "s6"))
    situations = table_rows(section("states.html", "s5"))
    rev_tr = table_rows(section("transitions.html", "s2"))
    node_tr = table_rows(section("transitions.html", "s3"))
    modes = table_rows(section("safety.html", "s10"))

    expect = [("revision states", rev_states, 21), ("node states", node_states, 12),
              ("events", events, 24), ("situations", situations, 9),
              ("revision transitions", rev_tr, 56), ("node transitions", node_tr, 24),
              ("failure modes", modes, 14)]
    bad = [f"{n}: got {len(r)}, expected {e}" for n, r, e in expect if len(r) != e]
    if bad:
        sys.exit("NOTHING WRITTEN — the pages moved:\n  " + "\n  ".join(bad))

    known = {r[0] for r in rev_states} | {r[0] for r in node_states}
    transitions, unresolved = write_transitions(rev_tr, node_tr, known)
    lint(rev_states, node_states, events, rev_tr, node_tr)
    trace_schema_lint(known, events)
    if drift := package_tally():
        sys.exit('NOTHING WRITTEN — modeling.html grades itself three ways:\n  '
                 + '\n  '.join(drift))

    files = {
        "transitions.yaml": transitions,
        "guards.yaml": write_guards(),
        "failure-scenarios.yaml": write_failures(situations, modes),
        "state-machine-revision.mmd": write_mermaid(rev_tr, known, "Revision state machine", "AwaitingBrief"),
        "state-machine-node.mmd": write_mermaid(node_tr, known, "Node state machine", "Planned"),
    }
    # GitHub shows .mmd as plain text but renders fenced mermaid in Markdown, so the
    # same two diagrams are emitted again here — generated, never hand-copied.
    files["diagrams.md"] = (
        "# State machines\n\n"
        "Generated from the tables in `../transitions.html` by `export-model.py` on " + STAMP + ".\n"
        "Do not edit: change `../transitions.html` and re-run the exporter.\n\n"
        "## Revision machine\n\n```mermaid\n"
        + files["state-machine-revision.mmd"] + "```\n\n"
        "## Node machine\n\n```mermaid\n"
        + files["state-machine-node.mmd"] + "```\n\n"
        "## Context\n\nHand-maintained in `context-diagram.mmd`; reproduced here so it renders.\n\n"
        "```mermaid\n" + (HERE / "context-diagram.mmd").read_text(encoding="utf-8") + "```\n")

    for name, body in files.items():
        (HERE / name).write_text(body, encoding="utf-8")
        print(f"  ✓ {name}  ({len(body.splitlines())} lines)")
    print(f"\n{len(unresolved)} endpoints could not be resolved to a state name "
          f"— listed under open_questions in transitions.yaml")


if __name__ == "__main__":
    main()
