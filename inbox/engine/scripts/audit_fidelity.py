#!/usr/bin/env python3
"""Fidelity + coverage audit for a YouTube capture note against its sibling transcript.

Catches the failure modes validate_note.py cannot see:
  1. a quote that is not verbatim in the transcript (paraphrase dressed as a quote)
  2. a [mm:ss] cited in the note that does not exist as a transcript line
  3. runtime the digest silently dropped (gaps between Timestamp ranges)
  4. summary bullets and deep-dive sections out of 1:1
  5. a quote lifted from outside the range its own section declares

Usage:  python3 audit_fidelity.py <note.md>
Exit 0 = clean, 1 = problems found (fix them before presenting the note).
"""
import re
import sys
from pathlib import Path

GAP_LIMIT = 30          # seconds — a hole longer than this means a segment was dropped
MIN_COVERAGE = 0.90     # union of Timestamp ranges / runtime
RANGE_SLACK = 2         # seconds of tolerance when testing a quote against its section's range

# --- thin-section check (added 2026-09-12) --------------------------------
# Coverage counts the WIDTH of declared ranges, so a note can tile its whole runtime
# with a handful of sections and score 100% while saying almost nothing. Measured across
# the 140 auditable notes in the library: healthy sections run 40–600 prose chars per
# declared minute; the tiled ones sit under 25 with ranges of many minutes.
THIN_RANGE = 300        # seconds — only judge density on sections claiming this much runtime
THIN_CHARS_PER_MIN = 25 # prose chars per declared minute below which a section is a shell

# --- rules that only apply to notes captured on/after this date ----------
# Older notes predate the rule; failing 300 backlog notes retroactively helps nobody.
RULE_DATE = "2026-09-12"

# --- template-fill checks (added 2026-09-19) -----------------------------
# Two notes on 2026-09-19 passed every check above while saying nothing: one repeated the
# same two paragraphs in all 18 sections, the other quoted the first transcript line of each
# 4-minute slice. Each signal below was measured over the 159 auditable notes; each fired on
# the offending note and on no note captured since the date the old checks took effect.
TEMPLATE_RULE_DATE = "2026-09-19"
SLICE_MIN_SECTIONS = 8   # below this, near-equal sections can happen honestly
SLICE_MAX_CV = 0.10      # spread of section lengths; real topic shifts vary far more
QUOTE_AT_START_MIN_SECTIONS = 5
QUOTE_AT_START_MAX = 0.8 # next-highest note in the library scored 0.5
# A range often starts between transcript lines, so a first-line quote lands 1–4 s after the
# start. Exact matching let 2026-09-21's Thiel note (every quote = its range's first line)
# score 0.73. With this slack it scores 1.00; no note captured since the rule date moves
# past 0.5 except that one.
QUOTE_AT_START_SLACK = 5 # seconds
# Quotes sampled off a clock instead of picked for meaning: 2026-09-23's maison note put all
# 27 quotes at mm:00–mm:09 (chance ≈ 0.17). Over 209 auditable notes, every note ≥ 0.8 was
# template fill (maison, pramy, 260909, 260827 ×2); the next-highest scored 0.62.
ROUND_MINUTE_SECS = 10
ROUND_MINUTE_MIN_QUOTES = 8
ROUND_MINUTE_MAX = 0.8
# A long range must be anchored in both halves. On 2026-09-19 a section claimed
# [78:19-94:37] and quoted only 93:28 — 14 minutes of other topics sat behind a widened
# range. A rule, not a detector: clustered anchors are normal in the library (most long
# sections cite 1–2 quotes), so the only honest fix is to require one per half.
LONG_RANGE = 600         # seconds
# Filler that interpolates the timestamp instead of saying what was said — "การเข้าใจบริบทที่
# 06:18 เป็นสิ่งสำคัญมากๆ ในช่วงนี้" (2026-09-20). Unique per section, so the duplicate check
# above cannot see it; with the numbers masked the sections collapse onto each other.
DIGITS = re.compile(r"\d+")
# One sentence pasted twice inside a paragraph, to clear the chars-per-minute floor.
ECHO_MIN = 20            # characters of the repeated run

# --- article translation check -------------------------------------------
# Thai renders English roughly 1 char per source word or denser; a faithful translation of
# an N-word page lands well above 2N characters. The 2026-09-11 failure (a "Full Translation"
# covering ~10% of the page) scored 0.5.
MIN_TH_CHARS_PER_SOURCE_WORD = 2.0


def norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("’", "'")
    s = s.replace("‘", "'").replace("—", "--").replace('\\"', '"')
    return re.sub(r"\s+", " ", s).strip()


def secs(ts: str) -> int:
    parts = [int(p) for p in ts.split(":")]
    return parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt(t: int) -> str:
    return f"{t // 60:02d}:{t % 60:02d}"


CONTEXT_LINES = 3  # transcript lines shown either side of a failing stamp


def context(lines: list[str], t: int, mark: str = "") -> str:
    """The transcript around second t, so the agent can fix a failure from this output.

    Without it, every failing quote sent the agent to `grep` the transcript for context
    — a fresh shell command each time, i.e. an approval popup (2026-09-19, 7 of them)."""
    stamps = [secs(l[1:l.index("]")]) for l in lines]
    i = min(range(len(stamps)), key=lambda k: abs(stamps[k] - t))
    lo, hi = max(0, i - CONTEXT_LINES), min(len(lines), i + CONTEXT_LINES + 1)
    rows = [f"        {'→' if k == i else ' '} {lines[k]}" for k in range(lo, hi)]
    return ("\n      " + mark if mark else "") + "\n" + "\n".join(rows)


def locate(lines: list[str], quote: str):
    """Second of the transcript line where the quote's opening words really occur, if any."""
    head = norm(quote)[:14]
    if len(head) < 8:
        return None
    for l in lines:
        if head in norm(re.sub(r"^\[[\d:]+\]\s*-?\s*", "", l)):
            return secs(l[1:l.index("]")])
    return None


def captured_on_or_after(note: str, date: str) -> bool:
    m = re.search(r"^captured:\s*\"?(\d{4}-\d{2}-\d{2})", note, re.M)
    return bool(m) and m.group(1) >= date


def prose_chars(block: str) -> int:
    """Body prose of one deep-dive section: the digest itself, minus its scaffolding.

    Drops headings, the Timestamp block, quote lines and tip lines, so what is left is
    what the section actually SAYS about the runtime it claims."""
    keep = []
    for line in block.splitlines()[1:]:
        s = line.strip()
        if not s or s.startswith(("#", "* [", "**Timestamp", "**Actionable", "---")):
            continue
        if re.match(r'^[-*]\s+"', s) or re.match(r"^\d+\.\s+\*\*", s):
            continue
        keep.append(s)
    return len(re.sub(r"\s+", "", " ".join(keep)))


def audit_article(note_file: Path, note: str) -> int:
    """Articles have no transcript; their ground truth is _sources/<slug>.md.

    Without that file nothing can check the Full Translation against the page — which is
    exactly how a note whose translation covered ~10% of its source passed every check."""
    src_file = note_file.parent / "_sources" / note_file.name
    problems = []
    if not src_file.exists():
        if captured_on_or_after(note, RULE_DATE):
            print(f"FAIL  no sibling source at {src_file} — save the extracted page text "
                  f"(article-capture step 5) or this note cannot be audited")
            return 1
        print(f"{note_file.name}: no sibling source (captured before {RULE_DATE}) — skipped")
        return 0

    source_words = len(src_file.read_text(encoding="utf-8").split())
    ft = re.split(r"^## Full Translation.*$", note, maxsplit=1, flags=re.M)
    if len(ft) < 2:
        problems.append("no `## Full Translation (TH)` section")
        th_chars = 0
    else:
        th_chars = len(re.sub(r"\s+", "", ft[1]))
    ratio = th_chars / source_words if source_words else 0
    if ratio < MIN_TH_CHARS_PER_SOURCE_WORD:
        problems.append(
            f"translation is {th_chars} chars for a {source_words}-word source "
            f"({ratio:.1f} chars/word, need >={MIN_TH_CHARS_PER_SOURCE_WORD}) — translate the "
            f"WHOLE page in order; do not summarize under that heading")

    quotes = re.findall(r'^[-*]\s+"(.+?)"\s*$', note, re.M)
    src_norm = norm(src_file.read_text(encoding="utf-8"))
    for q in quotes:
        if len(norm(q)) >= 12 and norm(q) not in src_norm:
            problems.append(f'quote not verbatim in source: "{q[:70]}…"')

    print(f"{note_file.name}: {len(quotes)} quotes · translation {th_chars} chars "
          f"/ {source_words} source words ({ratio:.1f})")
    for p in problems:
        print(f"  FAIL  {p}")
    print("clean" if not problems else f"{len(problems)} problem(s) — fix before presenting the note")
    return 1 if problems else 0


def audit_social(note_file: Path, note: str) -> int:
    """Long social posts are staged verbatim by `capture_queue.py social`; the model never
    re-types them. Every quote must then be found in that file (2026-09-25: a re-typed raw
    invented half of a post and the digest was built on it)."""
    src_file = note_file.parent / "_sources" / note_file.name
    if not src_file.exists():
        print(f"{note_file.name}: no _sources/ file (short post, raw kept in-note) — skipped")
        return 0
    src_norm = norm(src_file.read_text(encoding="utf-8"))
    quotes = re.findall(r'^[-*>]\s+`?"(.+?)"`?\s*$', note, re.M)
    problems = [f'quote not verbatim in source: "{q[:70]}…"'
                for q in quotes if len(norm(q)) >= 12 and norm(q) not in src_norm]
    print(f"{note_file.name}: {len(quotes)} quotes checked against {src_file.name}")
    for p in problems:
        print(f"  FAIL  {p}")
    print("clean" if not problems else f"{len(problems)} problem(s) — copy quotes from the source file")
    return 1 if problems else 0


def main(note_path: str) -> int:
    note_file = Path(note_path)
    note = note_file.read_text(encoding="utf-8")
    if "article" in [p.lower() for p in note_file.parts]:
        return audit_article(note_file, note)
    if "social" in [p.lower() for p in note_file.parts]:
        return audit_social(note_file, note)
    tr_file = note_file.parent / "_transcripts" / note_file.name
    if not tr_file.exists():
        print(f"FAIL  no sibling transcript at {tr_file} — slug must match the note")
        return 1

    tr = tr_file.read_text(encoding="utf-8")
    lines = [l for l in tr.splitlines() if re.match(r"^\[\d{1,3}:\d\d(:\d\d)?\]", l)]
    if not lines:
        print(f"FAIL  {tr_file.name} has no [mm:ss] lines")
        return 1
    stamps = {l[1:l.index("]")] for l in lines}
    flat = norm(" ".join(re.sub(r"^\[[\d:]+\]\s*-?\s*", "", l).strip() for l in lines))

    problems = []

    # 1 + 2 — quote fidelity and timestamp existence
    quotes = list(re.finditer(r'^- "(.+)" \[([\d:]+)\]\s*$', note, re.M))
    for m in quotes:
        # An empty or near-empty quote passes the substring test trivially ("" is inside
        # every string), so it would sail through as "verbatim" while carrying nothing.
        if len(norm(m.group(1))) < 8:
            problems.append(f'quote [{m.group(2)}] is empty/too short to be a quote: "{m.group(1)}"')
        elif norm(m.group(1)) not in flat:
            at = locate(lines, m.group(1))
            where = (context(lines, at, f"its opening words occur at [{fmt(at)}]:") if at is not None
                     else context(lines, secs(m.group(2)), f"transcript around [{m.group(2)}]:"))
            problems.append(f'quote not verbatim in transcript [{m.group(2)}]: "{m.group(1)[:70]}…"'
                            f" — copy it from the lines below, joining line breaks with ONE space"
                            + where)
        if m.group(2) not in stamps:
            problems.append(f"quote cites [{m.group(2)}] — not a line in the transcript"
                            + context(lines, secs(m.group(2)), "nearest real lines (→ = closest):"))

    quoted = {m.group(2) for m in quotes}
    for ts in sorted(set(re.findall(r"\[(\d{1,3}:\d\d(?::\d\d)?)\]", note))):
        if ts not in stamps and ts not in quoted:
            problems.append(f"[{ts}] cited in the note is not a line in the transcript"
                            + context(lines, secs(ts), "nearest real lines (→ = closest):"))

    # 5 — every quote must sit inside a Timestamp range its OWN section declares.
    # Checks 1+2 prove a quote is real and its stamp exists somewhere in the transcript;
    # neither proves it belongs to the section quoting it. A quote lifted from 28 minutes
    # away is verbatim, cites a real line, and still sends a reader who jumps to the
    # declared range somewhere nothing of the sort was said — which is the whole point of
    # citing a range. A section may declare SEVERAL ranges; the quote need only land in one.
    dd = re.split(r"^## Deep Dive.*$", note, maxsplit=1, flags=re.M)
    spans, quoted_sections, quotes_at_start = [], 0, 0
    para_sections: dict[str, list[str]] = {}
    if len(dd) == 2:
        deep = re.split(r"^## Source", dd[1], maxsplit=1, flags=re.M)[0]
        for block in re.split(r"^## ", deep, flags=re.M)[1:]:
            title = block.splitlines()[0].strip()
            for line in block.splitlines()[1:]:
                s = re.sub(r"\s+", " ", line.strip())
                if len(s) > 60 and not s.startswith(("-", "*", "#", ">")):
                    para_sections.setdefault(DIGITS.sub("#", s), []).append(title)
                    if captured_on_or_after(note, TEMPLATE_RULE_DATE):
                        echo = re.search(r"(.{%d,}?)\s*\1" % ECHO_MIN, s)
                        if echo:
                            problems.append(
                                f"§{title[:44]} repeats the same sentence inside one paragraph: "
                                f"\"{echo.group(1).strip()[:60]}…\" — padding, not content. Say what "
                                f"the speaker said in that stretch, or shorten the section.")
            rngs = [(secs(a), secs(b)) for a, b in
                    re.findall(r"^\*\s*\[([\d:]+)-([\d:]+)\]", block, re.M)]
            if not rngs:
                # Every per-section check below reads these ranges, so an unparseable
                # Timestamp block silently disabled all of them — one note on 2026-09-20
                # wrote `**Timestamp:** [00:02-05:07]` inline and skipped the lot.
                if captured_on_or_after(note, TEMPLATE_RULE_DATE):
                    problems.append(
                        f"§{title[:44]} has no readable Timestamp range. Write it as its own "
                        f"bullet under **Timestamp:** — `* [mm:ss-mm:ss] what this stretch covers` "
                        f"— or this section is exempt from every coverage and quote check.")
                continue
            spans.append(sum(hi - lo for lo, hi in rngs))
            if captured_on_or_after(note, TEMPLATE_RULE_DATE):
                body = re.sub(r"^\*\s*\[[\d:]+-[\d:]+\].*$", "", block, flags=re.M)
                anchors = [secs(x) for x in re.findall(r"\[(\d{1,3}:\d\d(?::\d\d)?)\]", body)]
                for lo, hi in rngs:
                    if hi - lo < LONG_RANGE:
                        continue
                    mid = (lo + hi) // 2
                    if not (any(lo - RANGE_SLACK <= a < mid for a in anchors)
                            and any(mid <= a <= hi + RANGE_SLACK for a in anchors)):
                        half = ("first" if not any(lo - RANGE_SLACK <= a < mid for a in anchors)
                                else "second")
                        a_, b_ = (lo, mid) if half == "first" else (mid, hi)
                        problems.append(
                            f"§{title[:44]} claims [{fmt(lo)}-{fmt(hi)}] ({(hi - lo) // 60} min) but "
                            f"nothing in it cites the {half} half [{fmt(a_)}-{fmt(b_)}]. Read that "
                            f"stretch: if it is a different topic, give it its own section; if it is "
                            f"this one, quote what is said there. Never narrow the claim by widening "
                            f"a neighbour." + context(lines, (a_ + b_) // 2, f"middle of [{fmt(a_)}-{fmt(b_)}]:"))
            block_quotes = re.findall(r'^- "(.+)" \[([\d:]+)\]\s*$', block, re.M)
            if block_quotes:
                quoted_sections += 1
                starts = {lo for lo, _ in rngs}
                quotes_at_start += all(any(0 <= secs(ts) - s <= QUOTE_AT_START_SLACK for s in starts)
                                       for _, ts in block_quotes)
            # A section that claims minutes of runtime and says almost nothing about it is
            # how a tiled note reaches 100% coverage. Judge only sections claiming real time.
            span = sum(hi - lo for lo, hi in rngs)
            if span >= THIN_RANGE:
                cpm = prose_chars(block) / (span / 60)
                if cpm < THIN_CHARS_PER_MIN:
                    problems.append(
                        f"§{title[:44]} claims {span // 60}m{span % 60:02d}s but its body is "
                        f"{prose_chars(block)} chars ({cpm:.0f}/min) — either the section never "
                        f"covers that stretch (go read it and split the section) or the range is "
                        f"wider than what it discusses. Do NOT pad the text; narrow the range or "
                        f"write what is actually there.")

            # Every Actionable Tip must carry the [mm:ss] of the line that says it, inside this
            # section's range — the mechanical half of "no invented advice".
            if captured_on_or_after(note, RULE_DATE):
                for tip in re.findall(r"^\d+\.\s+\*\*.+?\*\*.*$", block, re.M):
                    m = re.search(r"\[(\d{1,3}:\d\d(?::\d\d)?)\]\s*$", tip)
                    if not m:
                        problems.append(
                            f"§{title[:44]} tip has no [mm:ss] anchor: \"{tip.strip()[:60]}…\" — "
                            f"a tip must cite the line where the speaker says it, or be deleted")
                        continue
                    t = secs(m.group(1))
                    if not any(lo - RANGE_SLACK <= t <= hi + RANGE_SLACK for lo, hi in rngs):
                        problems.append(
                            f"§{title[:44]} tip cites [{m.group(1)}], outside this section's range")

            for q, ts in re.findall(r'^- "(.+)" \[([\d:]+)\]\s*$', block, re.M):
                t = secs(ts)
                if any(lo - RANGE_SLACK <= t <= hi + RANGE_SLACK for lo, hi in rngs):
                    continue
                declared = " ".join(f"[{fmt(lo)}-{fmt(hi)}]" for lo, hi in rngs)
                problems.append(
                    f"quote [{ts}] is outside the range its own section declares {declared} "
                    f'— §{title[:44]} · "{q[:44]}…". Quote from inside the range, or move '
                    f"the quote to the section that really covers it (do NOT widen the range)."
                    + context(lines, (rngs[0][0] + rngs[0][1]) // 2,
                              f"middle of this section's range {declared}:"))

    # 6 — template fill: text that is the same whatever the video said
    if captured_on_or_after(note, TEMPLATE_RULE_DATE):
        for para, where in para_sections.items():
            # Distinct titles, 3+: some older notes carry one section twice under the same
            # heading, which is a different defect from filler shared across topics.
            where = list(dict.fromkeys(where))
            if len(where) >= 3:
                problems.append(
                    f"the same paragraph appears in {len(where)} sections "
                    f"(§{where[0][:30]}, §{where[1][:30]}…): \"{para[:60]}…\" — each section must "
                    f"say what THAT stretch of the video says. Go read it; do not reword the filler.")
        if len(spans) >= SLICE_MIN_SECTIONS:
            mean = sum(spans) / len(spans)
            cv = (sum((s - mean) ** 2 for s in spans) / len(spans)) ** 0.5 / mean if mean else 0
            if cv < SLICE_MAX_CV:
                problems.append(
                    f"{len(spans)} sections of near-identical length ({min(spans)}–{max(spans)}s) — "
                    f"that is the clock, not the topics. Walk the transcript and cut where the "
                    f"speaker changes subject.")
        if (quoted_sections >= QUOTE_AT_START_MIN_SECTIONS
                and quotes_at_start / quoted_sections >= QUOTE_AT_START_MAX):
            problems.append(
                f"{quotes_at_start} of {quoted_sections} sections quote only the FIRST line of their "
                f"range — quotes chosen by position, not meaning. Pick the line that carries the "
                f"section's point.")
        qsecs = [secs(m.group(2)) for m in quotes]
        if len(qsecs) >= ROUND_MINUTE_MIN_QUOTES:
            on_minute = sum(t % 60 < ROUND_MINUTE_SECS for t in qsecs)
            if on_minute / len(qsecs) >= ROUND_MINUTE_MAX:
                problems.append(
                    f"{on_minute} of {len(qsecs)} quotes sit at mm:00–mm:0{ROUND_MINUTE_SECS - 1} — "
                    f"quotes sampled off the clock, not chosen for meaning. Read each section's "
                    f"stretch and quote the line that carries its point.")

    # 4 — 1:1 between summary bullets and deep-dive sections
    sm_block = re.split(r"^## Deep Dive", note, maxsplit=1, flags=re.M)[0]
    bullets = len(re.findall(r"^\* \[[\d:,\s-]+\]", sm_block, re.M))  # a bullet may cite several stamps
    sections = note.count("\n### คอนเซปหลัก")
    if bullets != sections:
        problems.append(f"{bullets} summary bullets vs {sections} deep-dive sections — must be 1:1")

    # 3 — coverage of the runtime
    dur = re.search(r"^duration:\s*\"?([\d:]+)\"?\s*$", note, re.M)
    runtime = secs(dur.group(1)) if dur else secs(max(stamps, key=secs))
    ranges = sorted((secs(a), secs(b)) for a, b in
                    re.findall(r"\[([\d:]+)-([\d:]+)\]", note))
    merged: list[list[int]] = []
    for s, e in ranges:
        if merged and s <= merged[-1][1] + 5:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    covered = sum(e - s for s, e in merged)
    pct = covered / runtime if runtime else 0

    gaps = []
    if merged:
        if merged[0][0] > GAP_LIMIT:
            gaps.append((0, merged[0][0]))
        gaps += [(a[1], b[0]) for a, b in zip(merged, merged[1:]) if b[0] - a[1] > GAP_LIMIT]
        if runtime - merged[-1][1] > GAP_LIMIT:
            gaps.append((merged[-1][1], runtime))
    for s, e in gaps:
        problems.append(f"uncovered {fmt(s)}-{fmt(e)} ({e - s}s) — read that stretch; what did the digest drop?")
    if pct < MIN_COVERAGE:
        problems.append(f"coverage {pct:.0%} of {fmt(runtime)} — need >={MIN_COVERAGE:.0%}")

    print(f"{note_file.name}: {len(quotes)} quotes · {bullets} bullets/{sections} sections · coverage {pct:.0%}")
    for p in problems:
        print(f"  FAIL  {p}")
    print("clean" if not problems else f"{len(problems)} problem(s) — fix before presenting the note")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
