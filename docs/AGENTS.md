# docs/

Design docs and protocol research for nvim-agent. These are working notes for agents and maintainers, not user-facing documentation (that goes in the README and the skill's `SKILL.md`).

## Files

- `protocol-notes.md`: what we know about Neovim's msgpack-rpc API and how it behaves in practice. Read it before designing or changing any part of the skill.
- `design.md`: the skill's design: container choice, command surface, safety rules, and test plan.

## Conventions

- Tag every factual claim about Neovim behavior:
  - **Verified**: observed against a live nvim with a script in `probes/`. Name the probe or the experiment.
  - **Recalled**: from memory or docs not yet checked. Treat as a hypothesis.
- When you verify a Recalled claim, flip the tag and add the probe that verified it. When an observation contradicts the doc, fix the doc rather than appending a correction.
- Record the nvim version you tested against in the doc header. Behavior around blocking and the TUI/server split has changed across versions.
- Keep "Open questions" current: delete items once answered and move the answer into the body.
- One topic per file. Split a doc once it covers more than one decision.
