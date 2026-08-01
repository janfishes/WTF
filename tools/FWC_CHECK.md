# Weekly FWC regulation check

Instructions for the scheduled cloud agent that keeps `regs.json` current.
A person following these by hand should get the same result.

## What you are maintaining

`regs.json` holds the harvest limits the app's Season Guide prints:

```json
{ "updated": "MM/DD/YY",
  "source": "...",
  "species": { "trout": { "size": "...", "bag": "...", "closed": [], "waters": "state", "fwc": "spotted-seatrout", "note": "..." } } }
```

The app fetches this file on open and uses it whenever its `updated` date is
newer than the copy baked into the build. Publishing this file is therefore how
a corrected limit reaches every phone **without an app update** — which is the
entire reason the file exists. It is also the reason a wrong value here is worse
than a stale one: nobody reviews it before it ships.

## The water this app covers

Florida **Atlantic**, Volusia County, **Northeast zone** — the water north of
the NSB South Causeway in New Smyrna Beach.

- Use Atlantic numbers. **Never Gulf.** Several FWC pages lead with the Gulf
  section, and the two differ (king mackerel is 2 on the Atlantic, 3 in the
  Gulf; triggerfish is closed Jan–Apr in the Gulf and open year-round on the
  Atlantic). Getting this wrong is the single most likely failure.
- Where FWC splits by zone, the row carries the **Northeast** values and the
  `note` carries the **Indian River Lagoon** zone difference. That zone takes in
  Mosquito Lagoon and starts at the NSB South Causeway — both are inside the
  app's map, so the note is not optional. Today it matters for redfish
  (catch-and-release in the lagoon), seatrout (bag 2, closed Nov 1 – Dec 31) and
  snook (same season both zones).

## Field meanings

| field | meaning |
|---|---|
| `size` | short display string — `28" fork min (Greater)`, `15" to 19"`, `No size limit`. Lengths carry the inch mark. Total length unless it says fork. |
| `bag` | daily bag per person unless it says otherwise — `3 (none over 19")`, `1 (4 per vessel)`. |
| `closed` | month indexes, **0 = January**, for months with ANY harvest closure. A season that opens or closes mid-month blacks out the WHOLE month (flounder Oct 15 – Nov 30 → `[9,10]`). |
| `waters` | `state` = the limits govern inside the 3-mile Atlantic line only; `both` = the same limits hold beyond it in federal water. FWC usually says which ("state regulations extend into federal waters", "for state and federal waters"). |
| `fwc` | the page slug under `https://myfwc.com/fishing/saltwater/recreational/`, or `[["Spanish","spanish-mackerel"],["King","king-mackerel"]]` where one row covers two managed fish. |
| `note` | the one-line caveat that would otherwise make the row a lie — zone splits, permits, mini-seasons, prohibited species. |

House style: fish named inside a line are Title Case (`24" min Gag & Black`),
`&` is written `&amp;` because these strings are injected as HTML, and notes are
one sentence or two, never a paragraph.

## What to do

1. Fetch each species' FWC page — the slug is in that species' `fwc` field.
   `unregulated` covers bonito, jack and whiting; `permit` covers both permit
   and pompano. Plain `curl` works; the pages are server-rendered HTML with the
   numbers inside collapsible panels, so strip tags and read the text.
2. For each species, compare FWC's Atlantic / Northeast numbers against
   `regs.json`. Read the actual page text — do not pattern-match blindly, and do
   not trust a value you could not find on the page.
3. **If a page fails to load or you cannot find the numbers, leave that species
   exactly as it is** and say so in your report. A skipped species is a fine
   outcome; a guessed one is not.
4. If nothing moved: change nothing, commit nothing, and report "no changes".
   Do not bump `updated` just to show you ran.
5. If something moved:
   - Edit `regs.json` — the changed fields, and `updated` to today as MM/DD/YY.
   - Add an entry at the top of `REGS_CHANGELOG.md` under a `## MM/DD/YY`
     heading: one bullet per species, naming the old value, the new value, and
     the FWC page you read it from.
   - Commit both and push to `main`. Commit message: `Regs MM/DD/YY — <species>
     <what moved>`, plus a `Co-Authored-By: Claude` line.
   - Do **not** touch `index.html`, `BUILD_NUM`, or anything else. This job
     publishes data, never a build. The baked-in table in index.html is the
     offline fallback and is allowed to fall behind.
6. Sanity-check before pushing: `python3 -c "import json;d=json.load(open('regs.json'));print(d['updated'],len(d['species']),len(d['changes']))"`
   must print today's date, **23**, and a changes count one higher than before. The app ignores a file with fewer than 10
   species, so a truncated write would silently strand every phone on the old
   table.

## The notification

You do not send mail yourself. Pushing `regs.json` to `main` fires
`.github/workflows/regs-notify.yml`, which opens a GitHub issue titled
**FWC changes to WTC** carrying the changelog entry and the diff — and GitHub
mails the repo owner. That is the whole notification path, and it needs no
credentials, so do not try to send email another way.

Two things you owe that workflow:

- Put the human summary in `REGS_CHANGELOG.md` under a `## MM/DD/YY` heading.
  The workflow lifts the newest dated section verbatim into the issue, so write
  that section for someone reading it on a phone, not for a diff reader.
- Add the same summary to the `changes` array at the top of `regs.json`:
  `{"date": "MM/DD/YY", "lines": ["...", "..."]}`, newest first. That array is
  what the app shows behind the REGULATION CHANGES button under the season
  bars, so it is the only version of the story most people will ever see. Keep
  it to one or two plain sentences per change: which fish, what it was, what it
  is now.

## Report back

End your run with a short summary — what you checked, what moved, what you
skipped and why. If anything changed, lead with it in plain words: which fish,
old value, new value. The issue GitHub opens is what actually reaches Jan; this
summary is what he sees if he opens the run.

## Watch list

Things known to move mid-year, worth a closer look every run:

- **Executive-order closures.** FWC closes seasons by EO between rule cycles —
  Atlantic gag grouper closed Aug 2, 2026 that way. These appear as a banner at
  the top of the species page, not in the regulation table.
- **Atlantic red snapper**, whose season is announced annually.
- **Gag and black grouper**, which have separate season end dates.
- **Amberjack**, whose Atlantic closure has moved more than once.
- Any page that stops matching this document's description of its layout —
  FWC redesigns occasionally, and a parser that silently finds nothing looks
  exactly like a fishery with no rules.
