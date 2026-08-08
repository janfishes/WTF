# WTF Log — working rules

## Every push ships its paperwork

**No commit that changes the app goes up without a build number, a CHANGELOG.md
line, and a BUILD_NOTES.txt entry.** All four steps happen in the SAME commit as
the change — not "later", not batched at the end of a session. If several builds
land in one sitting, each one gets its own number and its own entry.

1. **Bump `BUILD_NUM`** in `index.html` (search "Build tag - ONE source of
   truth"). The `#buildStamp` div is rewritten at load from those constants —
   editing the div alone gets silently reverted. Bump `BUILD_DATE` too when the
   date has rolled over.
2. **`CHANGELOG.md`** — one line, newest first, under the right date heading:
   `- **vNNN** — Two Or Three Words` (title case).
3. **`BUILD_NOTES.txt`** — the full note, newest first, under a dashed rule:
   `Build YYYY-MM-DD · H:MM AM/PM EDT · vNNN · <same tl;dr as the changelog>`
   Body wrapped at ~78 columns. Write what changed, **why Jan asked for it**, and
   any gotcha the next person would otherwise rediscover the hard way. These
   notes are the app's memory — they get read months later.
4. **After pushing**, archive the build: copy `index.html` to
   `~/Documents/WTF Files/index<BUILD_NUM>.html`, and refresh the single current
   copy of `BUILD_NOTES.txt` in that same folder.

Also on Jan's ship checklist for any change that warrants it: update the in-app
**help** (the `sheet-note` paragraphs), and the map **attribution/credits** if
imagery or data sources changed.

If a build ever does go up without its entries, backfill them from the commit
diff rather than leaving the gap — v442–v447 (2026-08-05) shipped without
theirs and were reconstructed later that evening. A backfilled note says so in
its own first line, and a docs-only commit like that takes no build number of
its own (nothing in the app changed).

## Before you commit

Run `git status --short` and `git diff --stat` first. Another session can be
mid-build in this same working tree; committing blind sweeps their uncommitted
work into your commit. If that happens, fold both changes into the one build
number already claimed.

## Verifying a deploy

Deploys go live via GitHub Pages (`janfishes.github.io/WTF`, `max-age=600`,
~1–2 min build). Check with:

```
curl -s https://janfishes.github.io/WTF/index.html | grep -o "BUILD_NUM  = [0-9]*"
```

`sw.js` is stale-while-revalidate, so a new build **always** takes two opens on
a device by design — "it didn't update" is usually that, not a failed deploy.
The iPhone home-screen app has its own storage partition and needs its own two
opens.
