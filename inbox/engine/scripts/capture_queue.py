#!/usr/bin/env python3
"""capture_queue.py — the four fixed commands a capture agent runs.

    python3 inbox/engine/scripts/capture_queue.py dup
    python3 inbox/engine/scripts/capture_queue.py fetch
    python3 inbox/engine/scripts/capture_queue.py file
    python3 inbox/engine/scripts/capture_queue.py check

The command text never varies, so each one can be approved once in an IDE that
matches an "always allow" rule against the literal command string. The varying
part — the URL — arrives in a file the agent writes with its own file tool:

    inbox/engine/queue/<video_id>.url      one URL, one line

fetch  waits for the lock, then walks the queue ONE video at a time, so ten
       parallel agents produce one sequential fetch stream rather than ten
       concurrent hits (the 2026-09-17 HTTP 429). Output goes to
       work/<video_id>/, keyed by video id, so no two runs share a path.
file   pairs each fetched transcript with the note that carries its URL and
       writes _transcripts/<note-slug>.md, the sibling audit_fidelity.py needs.
check  runs the R4 gate over every capture note touched in the last DAYS days.
social stages a long social post from social-*.md as verbatim ground truth, then files it
       under the note's slug once the note exists (see cmd_social).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ENGINE = SCRIPTS.parent
VAULT = ENGINE.parents[1]
QUEUE = ENGINE / "queue"
WORK = ENGINE / "work"
LOCK = WORK / ".lock"
YOUTUBE = VAULT / "inbox" / "resources" / "youtube"

# One fetch at a time, spaced out: YouTube blocked this IP on 2026-09-17 when ten
# transcripts were pulled at once.
GAP_SECONDS = 20
RETRIES = 2
RETRY_BACKOFF = 60
LOCK_STALE_SECONDS = 1800
DAYS = 1


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def video_id(url: str):
    m = re.search(r"(?:v=|youtu\.be/|/(?:shorts|embed|live)/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


# ── fetch ─────────────────────────────────────────────────────────────────────

def take_lock() -> bool:
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        LOCK.mkdir()
        return True
    except FileExistsError:
        if time.time() - LOCK.stat().st_mtime > LOCK_STALE_SECONDS:
            print(f"(clearing a stale lock, older than {LOCK_STALE_SECONDS // 60} min)")
            LOCK.rmdir()
            LOCK.mkdir()
            return True
        return False


def fetch_one(url: str, vid: str) -> int:
    """Fetch metadata + transcript for one video into work/<vid>/."""
    out = WORK / vid
    out.mkdir(parents=True, exist_ok=True)

    dup = sh(["python3", str(SCRIPTS / "check_url.py"), url])
    (out / "duplicate_check.txt").write_text(dup.stdout + dup.stderr, encoding="utf-8")
    repairing = False
    if dup.returncode == 1:
        # A note without its sibling transcript is unauditable, so re-fetching the
        # transcript IS the fix — the "already captured" stop only protects the note.
        existing = note_for(vid)
        repairing = existing is not None and not (
            existing.parent / "_transcripts" / f"{existing.stem}.md").exists()
        if not repairing:
            print(dup.stdout.rstrip())
            print(f"  → SKIPPED {vid}: already in the vault. Nothing was fetched.")
            return 1
        print(f"  ↻ {existing.name} exists but its transcript is missing — fetching that only.")

    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    cmd = [uv, "run", "--project", str(ENGINE), "python", str(SCRIPTS / "fetch_transcript.py"),
           url, "--transcript", str(out / "transcript.txt"),
           "--metadata", str(out / "metadata.json")]

    for attempt in range(1, RETRIES + 1):
        r = sh(cmd)
        if r.returncode == 0:
            break
        blocked = any(s in r.stderr for s in ("429", "Too Many Requests", "IpBlocked", "blocking"))
        print(f"  ✗ fetch failed for {vid} (attempt {attempt}/{RETRIES})")
        print("   ", r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "no stderr")
        (out / "fetch_error.txt").write_text(r.stderr, encoding="utf-8")
        if blocked:
            # Retrying an IP ban is what earns a longer one. Stop and wait it out.
            print("    YouTube has blocked this IP. Everything stays queued — run fetch "
                  "again in a few hours and it resumes where it stopped.")
            return 3
        if attempt == RETRIES:
            return 2
        time.sleep(RETRY_BACKOFF)

    meta = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    title, dur = meta.get("title", ""), meta.get("duration_string", "")

    # Same episode re-uploaded under a new id: the URL check above cannot see it,
    # only title + duration can.
    re_up = sh(["python3", str(SCRIPTS / "check_url.py"), url, title, dur]) if not repairing \
        else subprocess.CompletedProcess([], 0, "", "")
    if re_up.returncode == 1:
        (out / "duplicate_check.txt").write_text(re_up.stdout + re_up.stderr, encoding="utf-8")
        print(re_up.stdout.rstrip())
        print(f"  → {vid} fetched, but ASK THE USER before writing a note.")
        return 1

    print(f"  ✓ {vid}  {title}  [{dur}]")
    print(f"      transcript: {out / 'transcript.txt'}")
    print(f"      metadata:   {out / 'metadata.json'}")
    return 0


def wait_for_lock() -> None:
    """Block until this caller holds the lock.

    Returning early while another agent fetched made every parallel caller poll for its
    own video with `sleep N && fetch`, `while [ ! -f … ]` and `rm .lock` — each a new
    command string, so the approval popups came back, and several agents ended their
    turn "waiting" and never resumed (2026-09-19). The caller must get its video back
    from this one call."""
    announced = False
    while not take_lock():
        if not announced:
            print("Another agent is fetching — waiting for it to finish (this call returns "
                  "when your video is ready; do not re-run, sleep, or touch the lock)…", flush=True)
            announced = True
        time.sleep(5)


def report_ready() -> None:
    ready = [d for d in sorted(WORK.iterdir()) if (d / "transcript.txt").exists()] \
        if WORK.exists() else []
    if not ready:
        return
    print("\nReady in work/ (read transcript.txt + metadata.json for YOUR video id):")
    for d in ready:
        try:
            m = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
            print(f"  {d.name}  {m.get('title', '')}  [{m.get('duration_string', '')}]")
        except Exception:
            print(f"  {d.name}")


def cmd_fetch() -> int:
    QUEUE.mkdir(parents=True, exist_ok=True)
    wait_for_lock()
    try:
        return run_queue()
    finally:
        LOCK.rmdir()
        report_ready()


def run_queue() -> int:
    pending = sorted(QUEUE.glob("*.url"))
    if not pending:
        print("Queue is empty — nothing left to fetch.")
        return 0

    print(f"{len(pending)} queued · one at a time, {GAP_SECONDS}s apart\n")
    failed = 0
    for i, qf in enumerate(pending):
        url = qf.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        vid = video_id(url) or qf.stem
        print(f"[{i + 1}/{len(pending)}] {url}", flush=True)
        os.utime(LOCK)  # a waiter treats an old lock as abandoned; show this one is alive
        rc = fetch_one(url, vid)
        if rc == 3:
            print(f"\nStopped on an IP block. {len(pending) - i} still queued.")
            return 3
        if rc == 2:
            failed += 1          # keep it queued: a retry later costs nothing
        else:
            qf.unlink()
            (WORK / vid / "source.url").write_text(url + "\n", encoding="utf-8")
        if i + 1 < len(pending):
            time.sleep(GAP_SECONDS)
    print(f"\nDone. {len(pending) - failed} fetched, {failed} left in the queue.")
    return 0


# ── file ──────────────────────────────────────────────────────────────────────

def note_for(vid: str):
    """The capture note whose frontmatter url carries this video id."""
    for p in sorted(YOUTUBE.rglob("*.md")):
        if "_transcripts" in p.parts:
            continue
        head = p.read_text(encoding="utf-8", errors="replace")[:2000]
        m = re.search(r"^url:\s*(.+)$", head, re.M)
        if m and vid in m.group(1):
            return p
    return None


def prune_queue():
    """Drop queue entries whose note now exists — the article/social lanes never
    reach `fetch`, so nothing else clears what they queued for the dup check."""
    for qf in sorted(QUEUE.glob("*.url")) if QUEUE.exists() else []:
        url = qf.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        if sh(["python3", str(SCRIPTS / "check_url.py"), url]).returncode != 1:
            continue
        vid = video_id(url)
        note = note_for(vid) if vid else None
        if note and not (note.parent / "_transcripts" / f"{note.stem}.md").exists():
            continue          # a repair still waiting on its transcript
        qf.unlink()


def cmd_file() -> int:
    prune_queue()
    if not WORK.exists():
        print("Nothing fetched yet.")
        return 0
    dirs = [d for d in sorted(WORK.iterdir()) if d.is_dir() and d.name != ".lock"]
    if not dirs:
        print("Nothing fetched yet.")
        return 0

    for d in dirs:
        vid = d.name
        tr = d / "transcript.txt"
        if not tr.exists():
            if (d / "fetch_error.txt").exists():
                print(f"{vid}: fetch failed — it is still queued; run fetch again later.")
            else:
                shutil.rmtree(d)   # a duplicate skip: nothing was fetched, nothing to keep
                print(f"{vid}: skipped as already captured — cleared.")
            continue
        note = note_for(vid)
        if note is None:
            print(f"{vid}: no note carries this URL yet. Write the note, then run file again.")
            continue

        slug = note.stem
        url = (d / "source.url").read_text(encoding="utf-8").strip() if (d / "source.url").exists() \
            else f"https://www.youtube.com/watch?v={vid}"
        dest = note.parent / "_transcripts" / f"{slug}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# Raw transcript — cross-check for [[{slug}]]\n\n"
            f"> Verbatim fetched transcript, kept for verification only (NOT a capture note).\n"
            f"> Digest lives in [[{slug}]]. Jump here by timestamp to confirm any digest claim "
            f"is real, not fabricated.\n"
            f"> Source: {url}\n\n---\n\n"
        )
        dest.write_text(header + tr.read_text(encoding="utf-8"), encoding="utf-8")
        shutil.rmtree(d)
        print(f"✓ {dest.relative_to(VAULT)}")
        print(f"  paired with {note.relative_to(VAULT)}")
    return 0


# ── check ─────────────────────────────────────────────────────────────────────

def cmd_check() -> int:
    cutoff = time.time() - DAYS * 86400
    notes = [p for p in sorted((VAULT / "inbox" / "resources").rglob("*.md"))
             if not ({"_transcripts", "_sources", "raw"} & set(p.parts))
             and p.stat().st_mtime >= cutoff]
    if not notes:
        print(f"No capture note has changed in the last {DAYS * 24}h.")
        return 0

    bad = 0
    for n in notes:
        r = sh(["bash", str(SCRIPTS / "check_note.sh"), str(n)])
        out = (r.stdout or "").strip()
        ctx = ""
        if out:
            try:
                ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"].strip()
            except Exception:
                ctx = out
        if ctx:
            bad += 1
            print(f"✗ {n.relative_to(VAULT)}\n{ctx}\n")
        else:
            print(f"✓ {n.relative_to(VAULT)}")
    print(f"\n{len(notes)} checked · {bad} need work.")
    if bad:
        print("A gap is an order to go read that part of the source — never widen a "
              "Timestamp range to turn it green (R4).")
    return 1 if bad else 0


def cmd_dup() -> int:
    """Duplicate check for every queued URL — the article/social lanes' step 1b.

    (The youtube lane gets this inside `fetch`, before anything is downloaded.)
    """
    QUEUE.mkdir(parents=True, exist_ok=True)
    pending = sorted(QUEUE.glob("*.url"))
    if not pending:
        print(f"Queue is empty. Write one URL per file into {QUEUE.relative_to(VAULT)}/<id>.url")
        return 0
    dupes = 0
    for qf in pending:
        url = qf.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        r = sh(["python3", str(SCRIPTS / "check_url.py"), url])
        print(r.stdout.rstrip())
        if r.returncode == 1:
            dupes += 1
    return 1 if dupes else 0


SOCIAL = VAULT / "inbox" / "resources" / "social"
SOCIAL_SRC = SOCIAL / "_sources"
STAGED_PREFIX = "_staged-"
# A long post pasted into chat hit the 50,000-char cap and the model re-typed the rest from
# memory (2026-09-25). A post this size goes through a paste file instead, never chat.
CHAT_SAFE_CHARS = 5000
LINK_HEAVY = 10


def unwrap_fb(text: str) -> str:
    from urllib.parse import parse_qs, unquote, urlparse
    def repl(m):
        u = m.group(0)
        p = urlparse(u)
        if p.netloc.endswith("l.facebook.com") and p.path.startswith("/l.php"):
            u = unquote(parse_qs(p.query).get("u", [u])[0])
        return re.sub(r"([?&])fbclid=[^&\s]*&?", r"\1", u).rstrip("?&")
    return re.sub(r"https?://[^\s)>\]]+", repl, text)


def social_paste_files():
    """The user drops a long post into social-<anything>.md at the vault root (or in queue/)."""
    return sorted(list(VAULT.glob("social-*.md")) + list(QUEUE.glob("social-*.md")))


def cmd_social() -> int:
    """Stage a pasted social post as verbatim ground truth, then file it once the note exists.

    Run it twice, same text both times:
      1. before writing the note — stages each paste file as _sources/_staged-<name>.md,
         queues its URL for `dup`, prints size / links / suggested type.
      2. after writing the note — renames the staged source to _sources/<note-slug>.md
         and deletes the paste file (the verbatim copy now lives in _sources/).
    """
    SOCIAL_SRC.mkdir(parents=True, exist_ok=True)
    QUEUE.mkdir(parents=True, exist_ok=True)

    filed = 0
    for staged in sorted(SOCIAL_SRC.glob(STAGED_PREFIX + "*.md")):
        url = staged.read_text(encoding="utf-8").splitlines()[0].strip()
        notes = [n for n in SOCIAL.glob("*.md")
                 if re.search(r'^url:\s*"?' + re.escape(url) + r'"?\s*$',
                              n.read_text(encoding="utf-8"), re.M)]
        if not notes:
            print(f"· {staged.name} — staged, no note carries {url} yet")
            continue
        dest = SOCIAL_SRC / notes[0].name
        staged.replace(dest)
        paste = staged.name[len(STAGED_PREFIX):]
        for p in social_paste_files():
            if p.name == paste:
                p.unlink()
                print(f"  deleted paste file {p.relative_to(VAULT)}")
        print(f"✓ filed {dest.relative_to(VAULT)}  ← note {notes[0].name}")
        filed += 1

    staged_now = 0
    for p in social_paste_files():
        target = SOCIAL_SRC / (STAGED_PREFIX + p.name)
        if target.exists():
            continue
        text = p.read_text(encoding="utf-8").strip()
        lines = text.splitlines()
        if not lines or not re.match(r"https?://", lines[0].strip()):
            print(f"✗ {p.name}: first line must be the post URL — nothing staged")
            continue
        url = unwrap_fb(lines[0].strip())
        body = unwrap_fb("\n".join(lines[1:]).strip())
        target.write_text(url + "\n\n" + body + "\n", encoding="utf-8")
        (QUEUE / (p.stem + ".url")).write_text(url + "\n", encoding="utf-8")
        links = re.findall(r"https?://\S+", body)
        cut = [l for l in links if "..." in l or "…" in l]
        kind = ("C resource directory" if len(links) >= LINK_HEAVY
                else "B long essay" if len(body) > CHAT_SAFE_CHARS else "A short")
        print(f"◆ staged {p.name} → {target.relative_to(VAULT)}")
        print(f"  url   {url}\n  size  {len(body):,} chars · {len(links)} links · type {kind}")
        if cut:
            print(f"  ⚠ {len(cut)} links are cut short by Facebook's display (contain '...') — "
                  f"they cannot be opened as copied; say so in the note, never guess the full URL")
        staged_now += 1

    if not (filed or staged_now):
        print("Nothing to do. Paste the post into social-<yymmdd>.md at the vault root: "
              "line 1 = the post URL, then the post text.")
    return 0


CMDS = {"fetch": cmd_fetch, "file": cmd_file, "check": cmd_check, "dup": cmd_dup,
        "social": cmd_social}

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg not in CMDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(CMDS[arg]())
