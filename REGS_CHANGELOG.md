# Regulation changes — regs.json

Newest first. One entry per publish of `regs.json`, whether a person or the
scheduled FWC check made it. `regs.json` carries the limits the Season Guide
prints; the app fetches it on open and falls back to the copy baked into the
build when there is no signal.

Format: `## MM/DD/YY` then one bullet per species that moved, naming the old
value, the new value, and the FWC page it was read from.

## 08/01/26
- Initial split out of index.html (Build 285). Values are the ones verified
  against FWC's own species pages on 08/01/26 in Build 283 — see BUILD_NOTES.txt
  for the ten corrections that pass made.
