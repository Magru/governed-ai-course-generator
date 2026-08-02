# Governed AI Course Generator

Working specification for a governed AI course generator on an enterprise learning
platform: formal verification layers, managed moderation and retrieval, and
human-in-the-loop publication. Written as the final-project specification for the
AI Architect course.

Published at **https://magru.github.io/governed-ai-course-generator/**

## What's here

| File | Purpose |
|---|---|
| `index.html` | the cover — title, the system in one animated diagram, and the menu |
| `specification.html` | the specification itself, sixteen sections |
| `states.html` | state inventory — 21 revision states, 10 node states, invariants |
| `walkthrough.html` | one course from empty brief to publication in 24 steps |
| `configuration.html` | the seven configuration sources read at runtime |
| `transitions.html` | every legal move in both machines, with all 32 guards |
| `layers.html` | which engine owns which question, with runnable rules |
| `safety.html` | the action registry, prompt architecture, autonomy ladder |
| `spec.css` | the shared stylesheet — every page links it, nothing is duplicated |
| `spec.js` | shared behaviour — section rail, progress, copy buttons, diagram zoom |
| `.nojekyll` | tells GitHub Pages to serve the files as-is, without Jekyll processing |

Two pages are planned and not written yet: evaluation & red team, and the
implementation plan.

## Conventions

Page-specific CSS stays in an inline `<style>` block inside each page's body. That
block comes after `spec.css` in document order, so it still wins on the cascade —
which is what lets a page override the shared rules without touching them.

Diagrams are Mermaid, loaded as an ES module from a CDN. Everything else is
self-contained.

## Local preview

    python3 -m http.server 8791 --directory .

Then open http://localhost:8791. Opening the files directly over `file://` works for
everything except the Mermaid diagrams, which need an origin to load their module.
