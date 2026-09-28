#!/usr/bin/env python3
"""Pre-capture duplicate check (CLAUDE.md R4 sibling) — run BEFORE fetching or summarizing.

    python3 inbox/engine/scripts/check_url.py <URL>
    python3 inbox/engine/scripts/check_url.py <URL> "<title>" [duration]   # also catches re-uploads
    python3 inbox/engine/scripts/check_url.py <URL> --redate [YYYY-MM-DD]

Exit 0 = URL is new, go capture it.
Exit 1 = already captured. The user re-pasting a URL means they have NOT consumed that note
yet, so the note is not stale — their queue is. The task is to move the EXISTING note
forward to today's date, never to write a second note for the same source.

--redate does exactly that: rewrites `captured:`, renames the file's yymmdd prefix,
renames the sibling transcript, and repoints every [[wikilink]] in the vault.

Writing this as a script instead of a SKILL.md paragraph is deliberate: a rule in
markdown is advisory to three different vendors' models. This file is not.
"""
import re, subprocess, sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[3]
RES = VAULT / "inbox" / "resources"
SKIP = {"_transcripts", "_sources", "raw", "_wiki", "_learning"}


def norm(u: str) -> str:
    u = u.strip().strip('"').strip("'")
    m = re.search(r"(?:youtube\.com/.*[?&]v=|youtu\.be/|youtube\.com/(?:shorts|embed|live)/)([A-Za-z0-9_-]{6,})", u)
    if m:
        return "yt:" + m.group(1)
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("#", 1)[0]
    # Drop only tracking params. Never drop the whole query: Facebook carries the post
    # id there (facebook.com/photo?fbid=...), so stripping it collapses every FB post
    # onto one key and would block genuinely new captures as "already captured".
    if "?" in u:
        base, q = u.split("?", 1)
        keep = [kv for kv in q.split("&")
                if kv and not re.match(r"(utm_[a-z]+|fbclid|gclid|igshid|si|feature|ref|ref_src|mibextid)=", kv)]
        u = base.rstrip("/") + ("?" + "&".join(sorted(keep)) if keep else "")
    return u.rstrip("/").lower()


def notes():
    for p in sorted(RES.rglob("*.md")):
        if SKIP & set(p.relative_to(RES).parts):
            continue
        yield p


def _field(head: str, name: str) -> str:
    m = re.search(rf'^{name}:\s*"?(.*?)"?\s*$', head, re.M)
    return m.group(1).strip() if m else ""


def find(url: str, title: str = "", duration: str = ""):
    """Exact-URL hits first; then re-uploads — same title+duration under a new video id.

    A re-upload is the case a URL check cannot see: identical episode, different id
    (real case: Ookbee Pain Point EP.1 as kY7iQWJc1hE and nsaFIEKQkYE, both 1:07:16).
    """
    target = norm(url)
    hits, similar = [], []
    for p in notes():
        head = p.read_text(encoding="utf-8", errors="replace")[:2000]
        cap = _field(head, "captured") or "?"
        urls = [norm(m.group(1)) for m in re.finditer(r"^url:\s*(.+)$", head, re.M)]
        if target in urls:
            hits.append((p, cap))
        elif title and _field(head, "title") == title.strip() and (
            not duration or _field(head, "duration") == duration.strip()
        ):
            similar.append((p, cap))
    return hits, similar


def repoint(old: str, new: str):
    g = subprocess.run(["grep", "-rl", "--include=*.md", "-F", f"[[{old}", str(VAULT)],
                       capture_output=True, text=True)
    for h in g.stdout.splitlines():
        f = Path(h)
        if not f.is_file():
            continue
        t = f.read_text(encoding="utf-8")
        if f"[[{old}" in t:
            f.write_text(t.replace(f"[[{old}", f"[[{new}"), encoding="utf-8")


def redate(note: Path, date: str) -> Path:
    old = note.stem
    new = date[2:].replace("-", "") + old[6:] if re.match(r"^\d{6}-", old) else old
    t = note.read_text(encoding="utf-8")
    t = re.sub(r'^captured:\s*"?[\d-]+"?', f'captured: "{date}"', t, count=1, flags=re.M)
    note.write_text(t.replace(old, new) if new != old else t, encoding="utf-8")
    tr = note.parent / "_transcripts" / f"{old}.md"
    if new != old:
        if tr.exists():
            tr.write_text(tr.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
            tr.rename(note.parent / "_transcripts" / f"{new}.md")
        note = note.rename(note.parent / f"{new}.md")
        repoint(old, new)
    return note


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--redate"]
    if not args:
        print(__doc__)
        return 2
    url = args[0]
    date = next((a for a in args[1:] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a)),
                __import__("datetime").date.today().isoformat())
    title = next((a for a in args[1:] if not re.fullmatch(r"\d{4}-\d{2}-\d{2}|[\d:]+", a)), "")
    duration = next((a for a in args[1:] if re.fullmatch(r"[\d:]{4,}", a)), "")
    hits, similar = find(url, title, duration)
    if not hits:
        if similar:
            print("⚠️  POSSIBLE RE-UPLOAD — the URL is new, but a note has the same title"
                  + (" and duration" if duration else "") + ":")
            for p, cap in similar:
                print(f"    {p.relative_to(VAULT)}   captured: {cap}")
            print()
            print("A re-upload is the same content under a new video id. Ask the user whether to")
            print("re-date that note instead of capturing this URL — do not decide alone.")
            return 1
        print(f"NEW — no note carries {norm(url)}. Go capture it.")
        return 0

    print(f"⚠️  ALREADY CAPTURED — {norm(url)}")
    for p, cap in hits:
        print(f"    {p.relative_to(VAULT)}   captured: {cap}")
    if "--redate" not in sys.argv:
        print()
        print("DO NOT write a second note. Re-pasting a URL means this one is still unconsumed —")
        print("move it forward instead:")
        print(f"    python3 inbox/engine/scripts/check_url.py '{url}' --redate")
        print("Then tell the user which note was re-dated, and stop.")
        return 1

    for p, cap in hits:
        if cap == date:
            print(f"    already dated {date}: {p.relative_to(VAULT)}")
            continue
        new = redate(p, date)
        print(f"    re-dated {cap} -> {date}: {new.relative_to(VAULT)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
