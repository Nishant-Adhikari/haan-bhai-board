# Haan Bhai board — GitHub Pages (Phase 1 done, Phase 2 pending go-ahead)

## What this is
A self-contained GitHub Pages site for the Haan Bhai agent board (pixel look,
night mode default, three project panels). The page rebuilds itself from the
live HANDOFF.md files every 5 minutes and the browser re-fetches every 5 min.

## Files
- `index.html` — generated page, current as of Mon Nov 16, 2026 · 9:32 PM CT.
- `template.html` — the shared layout. Both the first build and the refresh
  script render from this file; edit the look here, never in index.html.
- `board-data.json` — the data baked into index.html (same schema the refresh
  script builds from the HANDOFFs).
- `refresh-board.py` — Mac-side refresh worker: reads the 3 HANDOFFs, runs
  `cmux tree --all` for worker liveness, renders template.html, validates the
  page (all 3 panels non-empty, no leftover tokens), and commits + pushes
  ONLY when the content changed. `--check` validates without writing.
- `com.nishant.haan-bhai-refresh.plist` — launchd job: runs refresh-board.py
  every 300s, RunAtLoad. Install on the Mac with:
  `cp com.nishant.haan-bhai-refresh.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.nishant.haan-bhai-refresh.plist`

## Phase 2 (needs a separate go-ahead)
1. Create the GitHub repo (suggested name: `haan-bhai-board`, public).
2. Copy this folder to `/Users/Nishant/haan-bhai-board/`, `git init`, add the
   remote, push main.
3. Enable GitHub Pages (Settings → Pages → Deploy from branch → main, / root).
4. Load the launchd plist above. Verify the live URL shows the current time
   in "As of" and the next 5-min refresh updates it.
5. The Talk to Goku panel posts to http://127.0.0.1:8765 — it works when the
   board is viewed on the Mac; elsewhere it shows a best-effort note.
