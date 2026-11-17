#!/usr/bin/env python3
"""Haan Bhai board refresh — Phase 2 worker (runs on the Mac).

Reads the three project HANDOFF.md files + `cmux tree --all`, regenerates
index.html from template.html, and commits + pushes ONLY when the content
changed. Never pushes an empty or broken page: the rendered HTML is
validated (all three project panels present and non-empty, no leftover
tokens) before anything is written.

Usage:
  # Normal Mac run (launchd, every 300s):
  python3 refresh-board.py
  # Render once from a data file (used to build the first index.html):
  python3 refresh-board.py --data board-data.json --template template.html --out index.html
  # Validate the render without writing or pushing:
  python3 refresh-board.py --check

Repo checkout on the Mac: /Users/Nishant/haan-bhai-board/
HANDOFF paths are the live project checkouts (see HANDOFF_PATHS below).
"""

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - very old Python
    ZoneInfo = None

REPO_DIR = Path("/Users/Nishant/haan-bhai-board")
HANDOFF_PATHS = {
    "flixkeep": Path("/Users/Nishant/Documents/codebase/flixkeep/HANDOFF.md"),
    "ahaan": Path("/Users/Nishant/Documents/codebase/Ahaan's portfolio/HANDOFF.md"),
    "vihaan": Path("/Users/Nishant/Documents/antigravity/friendly-oppenheimer/HANDOFF.md"),
}

# Items the queue parser cannot derive on its own. Each entry is only shown
# if the HANDOFF text actually mentions the feature (checked by _mentioned);
# otherwise it is dropped and a warning is printed. Keep this list short and
# honest: it is a fallback for records the workers write as prose, not as
# queue items.
KNOWN_DONE = {
    "flixkeep": [
        ("Scout-QA + TMDB fixes merged", "Nov 10", ["Scout-QA", "TMDB"]),
        ("Movie Starter Pack", "Done locally Nov 13, not merged", ["Starter Pack"]),
        ("Backend gaps from QA triage", "Done locally Nov 13, not merged", ["Backend gaps"]),
        ("Housekeeping: tests + Dependabot", "Done locally Nov 13, not merged", ["Housekeeping"]),
    ],
    "ahaan": [
        ("Bike + ice cream", "Published Nov 14", ["bike + ice cream", "bike-ice-cream"]),
        ("Aesop\u2019s Fables", "Published Nov 14", ["Aesop"]),
        ("Bike-speed boost", "Published Nov 16, merge 1b39ba5, Space = boost", ["bike-speed-boost", "bike speed boost"]),
    ],
    "vihaan": [
        ("Chess tactics trainer \u00b7 12 puzzles", "Published Nov 11", ["Chess Tactics Trainer"]),
        ("Publish: sub-navs + Room Life", "Live Nov 11", ["sub-navs", "Room Life"]),
        ("Road to State checklist", "Published Nov 11", ["Road to State checklist"]),
        ("Spelling Bee Master pack", "Published Nov 14, bank 162 words", ["Spelling Bee", "Master pack"]),
        ("Author\u2019s Room Ch 3 (tendons)", "Published Nov 14", ["Author's Room Ch 3", "authors-room-ch3"]),
        ("Cruise Ship Explorer", "Published Nov 10", ["Cruise Ship Explorer"]),
        ("Game Room", "Published Nov 9", ["Game Room"]),
    ],
}

# In-progress work that lives outside the numbered queue (e.g. a fix-check
# run the worker records as prose). Same mention-check rule as KNOWN_DONE.
KNOWN_IN_PROGRESS = {
    "flixkeep": [
        ("Mobile fix-check", "blocked", "BLOCKED",
         "Failed 3x, harness exit 1, worker diagnosing", ["mobile", "fix-check"]),
    ],
}

# Backlog text when a project's queue is empty.
EMPTY_BACKLOG_TEXT = "Queue clear \u2014 next feature to be discussed"


# ---------------------------------------------------------------- parsing

def _mentioned(text, needles):
    low = text.lower()
    return any(n.lower() in low for n in needles)


def _clean_title(raw):
    raw = raw.strip().strip("*").strip()
    raw = re.sub(r"^\d+\.\s*", "", raw)
    return raw


def parse_queue(text):
    """Parse the 'Next briefs' queue section.

    Returns (in_progress, backlog, done): lists of item dicts with
    text / tag / tag_label / note.
    """
    m = re.search(r"^## Next briefs.*?$", text, re.M | re.S)
    if not m:
        return [], [], []
    start = m.start()
    nxt = re.search(r"^## ", text[start + 10:], re.M)
    section = text[start:start + 10 + nxt.start()] if nxt else text[start:]
    in_progress, backlog, done = [], [], []
    for line in section.splitlines():
        if not re.match(r"^\d+\.\s", line.strip()):
            continue
        item = _parse_queue_line(line)
        if item is None:
            continue
        status = item.pop("_status")
        if status == "done":
            done.append(item)
        elif status == "in_progress":
            in_progress.append(item)
        else:
            backlog.append(item)
    return in_progress, backlog, done


# Queue lines use brief filenames as their title; show the friendly name.
FRIENDLY_TITLES = {
    "feature-brief-two-player.md": "Two-player mode",
    "feature-brief-country-book-v2.md": "Country Book v2",
    "feature-brief-vihaan-quad.md": "Vihaan\u2019s quad",
    "feature-brief-capitals-quiz.md": "Capitals Quiz",
    "feature-brief-reading-aesop-link.md": "Reading \u2192 Aesop link",
    "feature-brief-backend-newsletter-fixes.md": "Backend + newsletter fixes",
    "feature-brief-ask-reliability.md": "Fix Ask FlixKeep reliability",
    "feature-brief-dna-taste-pixel-grid.md": "Movie DNA taste-pixel grid",
    "feature-brief-harder-tactics.md": "Harder tactics Pack 2",
    "feature-brief-solar-system.md": "Solar system",
    "feature-brief-authors-room-count.md": "Author\u2019s Room count fix",
    "feature-brief-spelling-bee-world-champion.md": "Spelling Bee World Champion section",
    "feature-brief-bike-speed-boost.md": "Bike-speed boost",
    "feature-brief-bike-icecream.md": "Bike + ice cream",
    "feature-brief-aesops-fables.md": "Aesop\u2019s Fables",
}


def _parse_queue_line(line):
    line = line.strip()
    bold = re.search(r"\*\*(.+?)\*\*", line)
    if bold:
        title = bold.group(1).strip()
        rest = line[bold.end():]
    else:
        parts = re.split(r"\s—\s|\s-\s", line, maxsplit=1)
        title = _clean_title(parts[0])
        rest = parts[1] if len(parts) > 1 else ""
    title = FRIENDLY_TITLES.get(title.lower(), title)
    rest = rest.strip(" —-").strip()
    low = line.lower()
    surface = None
    sm = re.search(r"surface\s+(\d{10})", low)
    if sm:
        surface = sm.group(1)
    note = rest
    if surface:
        note = (note + f", surface {surface}").strip(", ")
    tag, tag_label, status = None, None, "backlog"
    if "published" in low:
        status, tag, tag_label = "done", None, None
    elif "complete locally" in low or "completed locally" in low:
        status, tag, tag_label = "done", "local", "LOCAL"
        note = "Done locally, not merged" + (f" — {note}" if note else "")
    elif "dispatched" in low or "in progress" in low or "active" in low:
        status, tag, tag_label = "in_progress", "working", "WORKING"
    return {"text": title, "tag": tag, "tag_label": tag_label, "note": note,
            "_status": status}


def cmux_states():
    """Map surface id -> state word from `cmux tree --all`.

    Lenient on format; returns {} when cmux is unavailable.
    """
    try:
        out = subprocess.run(["cmux", "tree", "--all"],
                             capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}
    text = out.stdout or ""
    states = {}
    for m in re.finditer(r"(1000090\d{3})", text):
        sid = m.group(1)
        window = text[max(0, m.start() - 200):m.end() + 200]
        for word in ("Action Required", "Working", "Idle", "Waiting"):
            if word.lower() in window.lower():
                states[sid] = word
                break
    return states


def build_data():
    """Build the board data dict from the live HANDOFFs + cmux tree."""
    states = cmux_states()
    data = {}
    for key, path in HANDOFF_PATHS.items():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"WARN: cannot read {path}: {exc}", file=sys.stderr)
            text = ""
        in_prog, backlog, done = parse_queue(text)
        # Known-done items, only if the HANDOFF actually mentions them.
        for title, note, needles in KNOWN_DONE.get(key, []):
            if not _mentioned(text, needles):
                print(f"WARN: {key}: KNOWN_DONE '{title}' not in HANDOFF, dropped",
                      file=sys.stderr)
                continue
            if any(d["text"] == title for d in done):
                continue
            tag = "local" if "not merged" in note else None
            done.append({"text": title, "tag": tag,
                         "tag_label": "LOCAL" if tag else None, "note": note})
        for title, tag, tag_label, note, needles in KNOWN_IN_PROGRESS.get(key, []):
            if not _mentioned(text, needles):
                print(f"WARN: {key}: KNOWN_IN_PROGRESS '{title}' not in HANDOFF, dropped",
                      file=sys.stderr)
                continue
            if any(d["text"] == title for d in in_prog):
                continue
            in_prog.append({"text": title, "tag": tag, "tag_label": tag_label,
                            "note": note})
        # Liveness: cmux state overrides the working tag for surfaced items.
        for item in in_prog:
            sm = re.search(r"surface (\d{10})", item.get("note") or "")
            if not sm:
                continue
            state = states.get(sm.group(1))
            if state == "Idle":
                item["tag"], item["tag_label"] = "idle", "IDLE"
            elif state in ("Action Required", "Waiting"):
                item["tag"], item["tag_label"] = "waiting", "WAITING"
            elif state == "Working" and item["tag"] in (None, "idle", "waiting"):
                item["tag"], item["tag_label"] = "working", "WORKING"
        data[key] = {"in_progress": in_prog, "backlog": backlog, "done": done}
    data["as_of"] = chicago_now()
    data["shared_status"] = (
        "CODEX &middot; GPT-6-LUNA &middot; MEDIUM &nbsp;&middot;&nbsp; "
        '<span class="tok">TOKENS 80% LEFT</span> &middot; resets Nov 18'
    )
    data["footer_note"] = (
        "Data: project HANDOFF.md files on the Mac, refreshed every 5 min. "
        "LOCAL = done locally, not merged or published yet."
    )
    return data


def chicago_now():
    if ZoneInfo is not None:
        now = datetime.now(ZoneInfo("America/Chicago"))
    else:
        now = datetime.now()
    return now.strftime("%a %b %d, %Y · %-I:%M %p CT")


# ---------------------------------------------------------------- rendering

def render_items(items, empty_text=None):
    if not items:
        if empty_text:
            return f'        <li class="empty">{empty_text}</li>\n'
        return ""
    out = []
    for it in items:
        tag = ""
        if it.get("tag") and it.get("tag_label"):
            tag = f' <span class="tag {it["tag"]}">{it["tag_label"]}</span>'
        note = f' <span class="note">&mdash; {it["note"]}</span>' if it.get("note") else ""
        out.append(f'        <li>{it["text"]}{tag}{note}</li>\n')
    return "".join(out)


def render(template_text, data):
    def items(project, section):
        return render_items(
            data[project][section],
            EMPTY_BACKLOG_TEXT if section == "backlog" else None)

    tokens = {
        "AS_OF": data["as_of"],
        "SHARED_STATUS": data["shared_status"],
        "FLIXKEEP_ENGINE": "<b>Codex</b>",
        "AHAAN_ENGINE": "<b>Codex</b>",
        "VIHAAN_ENGINE": "<b>Codex</b>",
        "FLIXKEEP_IN_PROGRESS": items("flixkeep", "in_progress"),
        "FLIXKEEP_BACKLOG": items("flixkeep", "backlog"),
        "FLIXKEEP_DONE": items("flixkeep", "done"),
        "AHAAN_IN_PROGRESS": items("ahaan", "in_progress"),
        "AHAAN_BACKLOG": items("ahaan", "backlog"),
        "AHAAN_DONE": items("ahaan", "done"),
        "VIHAAN_IN_PROGRESS": items("vihaan", "in_progress"),
        "VIHAAN_BACKLOG": items("vihaan", "backlog"),
        "VIHAAN_DONE": items("vihaan", "done"),
        "FOOTER_NOTE": data["footer_note"],
    }
    html = template_text
    for key, value in tokens.items():
        html = html.replace("{{" + key + "}}", value)
    return html


def validate(html):
    """Never push an empty or broken page. Returns a list of problems."""
    problems = []
    for panel in ("panel-flixkeep", "panel-ahaan", "panel-vihaan"):
        if f'id="{panel}"' not in html:
            problems.append(f"missing panel {panel}")
        else:
            section = html.split(f'id="{panel}"', 1)[1].split("</section>", 1)[0]
            if "<li>" not in section and "empty" not in section:
                problems.append(f"panel {panel} has no items")
    if "HAAN BHAI" not in html:
        problems.append("missing title")
    if '<meta http-equiv="refresh" content="300">' not in html:
        problems.append("missing 5-min meta refresh")
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if leftover:
        problems.append(f"unsubstituted tokens: {sorted(set(leftover))}")
    return problems


# ---------------------------------------------------------------- git

def git_push_if_changed(repo, html, data):
    index_path = repo / "index.html"
    data_path = repo / "board-data.json"
    old = index_path.read_bytes() if index_path.exists() else b""
    if old == html.encode("utf-8"):
        print("No change — nothing to commit.")
        return False
    problems = validate(html)
    if problems:
        print("REFUSING to write invalid page: " + "; ".join(problems),
              file=sys.stderr)
        return False
    index_path.write_text(html, encoding="utf-8")
    data_path.write_text(json.dumps(data, indent=2, sort_keys=True,
                                    ensure_ascii=False), encoding="utf-8")
    subprocess.run(["git", "add", "index.html", "board-data.json"],
                   cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m",
                    f"board: refresh {data['as_of']}"], cwd=repo, check=True)
    subprocess.run(["git", "push"], cwd=repo, check=True)
    print(f"Pushed board refresh ({data['as_of']}).")
    return True


# ---------------------------------------------------------------- main

def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Refresh the Haan Bhai board.")
    ap.add_argument("--repo", default=str(REPO_DIR))
    ap.add_argument("--data", help="Render from a data JSON file instead of HANDOFFs")
    ap.add_argument("--template", help="Template file (default: <repo>/template.html)")
    ap.add_argument("--out", help="Write HTML here instead of committing to the repo")
    ap.add_argument("--check", action="store_true",
                    help="Validate the render only; write and push nothing")
    args = ap.parse_args(argv)

    repo = Path(args.repo)
    template_path = Path(args.template) if args.template else repo / "template.html"
    template_text = template_path.read_text(encoding="utf-8")

    if args.data:
        data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    else:
        data = build_data()

    html = render(template_text, data)
    problems = validate(html)
    if problems:
        print("INVALID: " + "; ".join(problems), file=sys.stderr)
        return 1
    if args.check:
        print("Render valid; nothing written.")
        return 0
    if args.out:
        Path(args.out).write_text(html, encoding="utf-8")
        print(f"Wrote {args.out}")
        return 0
    try:
        git_push_if_changed(repo, html, data)
    except subprocess.CalledProcessError as exc:
        print(f"git step failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
