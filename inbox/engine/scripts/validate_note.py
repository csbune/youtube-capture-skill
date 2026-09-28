#!/usr/bin/env python3
"""Validate capture notes against the skill specs (youtube/article/social capture + wishlist-book).

Usage:
    python3 validate_note.py <file.md> [more files...]
    python3 validate_note.py --all          # scan all of inbox/resources/{youtube,article,social,wishlist/Books}

Exit code 0 = all files pass (warnings allowed), 1 = at least one ERROR.
Agents MUST run this on every note they save and fix ERRORs before finishing.
No dependencies — plain stdlib.
"""
import re
import sys
from pathlib import Path

RESOURCES = Path(__file__).resolve().parents[2] / "resources"

# Required keys (exact order). `creator` = the publisher (youtube channel / social page /
# blog+website). Optional keys (OPTIONAL_KEYS) come after, in that order.
KEY_SPECS = {
    "youtube": ["title", "url", "channel", "platform", "type", "captured", "status", "duration", "tags"],
    "article": ["title", "url", "channel", "platform", "type", "captured", "status", "published", "tags"],
    # social has no reliable channel in its data (share-link URLs) — channel is optional here,
    # backfilled per-post later; youtube/article require channel.
    "social":  ["title", "url", "platform", "type", "captured", "status", "tags"],
    "book":    ["type", "title", "author", "isbn", "cover", "link_amazon", "price", "tags"],
}
# Optional trailing keys. `idea owner` = the thinker whose framework the piece presents — even
# if only cited, not speaking; may be a list. `expressed_as` = [[note]] link to the composed
# note once this capture has been worked up. (`channel` = the publisher: youtube channel /
# blog+website / social page.)
OPTIONAL_KEYS = {
    "youtube": ["idea owner", "expressed_as"],
    "article": ["idea owner", "expressed_as"],
    "social":  ["channel", "idea owner", "expressed_as"],
    "book":    [],
}
STATUS_VALUES = {"captured", "drafted", "expressed"}

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def detect_kind(path: Path):
    parts = [p.lower() for p in path.parts]
    if "_transcripts" in parts or "_sources" in parts:
        return "skip"  # sibling ground-truth files (transcript / extracted article) are cross-check material, not notes
    if "wiki" in parts:
        return "skip"  # the wiki lane (raw/ + _wiki/ + _learning/) has its own shape, not a capture-note one
    if "books" in parts or "wishlist" in parts:
        return "book"
    for k in ("youtube", "article", "social"):
        if k in parts:
            return k
    return None


def parse_frontmatter(text):
    """Return (ordered list of (key, value), body) or (None, None).

    A YAML block list (a key with empty value followed by `- item` lines — Obsidian's
    native format for list properties like tags) is normalized to the inline form
    `[a, b, c]`, so downstream checks treat block-list and inline tags identically.
    """
    m = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", text, re.S)
    if not m:
        return None, None
    pairs = []
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line.startswith(("  ", "\t", "- ")):  # orphan list line with no parent key — skip
            i += 1
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            # empty scalar followed by `- item` lines → collect a block list into [a, b, c]
            if v == "" and i + 1 < len(lines) and lines[i + 1].lstrip().startswith("- "):
                items = []
                j = i + 1
                while j < len(lines) and lines[j].lstrip().startswith("- "):
                    items.append(lines[j].lstrip()[2:].strip().strip('"\''))
                    j += 1
                pairs.append((k, "[" + ", ".join(items) + "]"))
                i = j
                continue
            pairs.append((k, v))
        i += 1
    return pairs, m.group(2)


def check(path: Path):
    errors, warnings = [], []
    kind = detect_kind(path)
    if kind == "skip":
        return None, None  # signal: not a note, don't count or report
    if kind is None:
        return ["cannot detect note kind from path"], []
    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    if fm is None:
        return ["no YAML frontmatter block found"], []

    keys = [k for k, _ in fm]
    vals = dict(fm)
    # values may be quoted ("thinking") or bare (thinking) — Obsidian/agents vary; compare
    # quote-insensitively so scalar checks (type, platform, status) don't care about quoting.
    vals = {k: (v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v) for k, v in vals.items()}
    spec = KEY_SPECS[kind]

    # block-list tags are now normalized in parse_frontmatter (Obsidian-native form is fine).
    # Required keys must lead, in order; optional keys (author, expressed_as) may follow, in order.
    opt = OPTIONAL_KEYS.get(kind, [])
    if keys[:len(spec)] != spec:
        errors.append(f"required frontmatter keys/order must be {spec}, got {keys}")
    else:
        extra, oi = keys[len(spec):], 0
        for k in extra:
            while oi < len(opt) and opt[oi] != k:
                oi += 1
            if oi >= len(opt):
                errors.append(f"unexpected frontmatter key {k!r} — after the required keys only {opt} are allowed, in that order")
                break
            oi += 1

    # status enum + creator + expressed_as (captures only; book keeps its own rules)
    if kind in ("youtube", "article", "social"):
        st = vals.get("status", "").strip().strip('"')
        if st not in STATUS_VALUES:
            errors.append(f"status must be one of {sorted(STATUS_VALUES)}, got {st!r}")
        if kind in ("youtube", "article") and not vals.get("channel", "").strip().strip('"'):
            errors.append("channel must be filled (youtube channel / blog+website name)")
        if "expressed_as" in keys:
            ea = vals.get("expressed_as", "").strip().strip('"')
            if not re.match(r"^\[\[.+\]\]$", ea):
                warnings.append("expressed_as should be a wikilink to the composed note, e.g. [[my-note]]")
        elif st == "expressed":
            warnings.append("status is 'expressed' but there is no expressed_as link to the composed note")

    # type
    t = vals.get("type", "")
    if kind == "book":
        if t != "book":
            errors.append(f"type must be 'book', got {t!r}")
    elif t not in ("thinking", "building"):
        errors.append(f"type must be scalar 'thinking' or 'building', got {t!r}")

    # tags
    tags_raw = vals.get("tags", "")
    mt = re.match(r"^\[(.*)\]$", tags_raw)
    tags = [x.strip().strip('"\'') for x in mt.group(1).split(",")] if mt else []
    if kind == "book":
        if tags != ["wishlist", "book"]:
            errors.append(f"tags must be [wishlist, book], got {tags_raw!r}")
    else:
        if len(tags) != 3:
            errors.append(f"tags must be EXACTLY 3 concept tags, got {len(tags)}: {tags_raw!r}")
        for tag in tags:
            if tag in ("thinking", "building"):
                errors.append(f"tag {tag!r} is a content-TYPE — it belongs in type:, never in tags:")
            elif tag and not KEBAB.match(tag):
                warnings.append(f"tag {tag!r} is not lowercase-kebab-case")

    # dates
    if kind != "book":
        cap = vals.get("captured", "").strip('"')
        if not ISO.match(cap):
            errors.append(f"captured must be YYYY-MM-DD, got {cap!r}")
        # The yymmdd prefix is the capture date, never the upload date: the queue and the
        # library sort by it. Two notes captured 2026-09-19 were filed as 260212 and 260918.
        pre = re.match(r"(\d{6})-", path.name)
        if pre and ISO.match(cap) and cap >= "2026-09-19" and pre.group(1) != cap[2:].replace("-", ""):
            errors.append(f"filename starts {pre.group(1)} but captured is {cap} — the prefix is the "
                          f"CAPTURE date ({cap[2:].replace('-', '')}-…), not the upload date")
    if kind == "article":
        pub = vals.get("published", "").strip('"')
        if pub and not ISO.match(pub):
            errors.append(f"published must be YYYY-MM-DD or blank, got {pub!r}")
        if vals.get("platform") != "website":
            errors.append("platform must be 'website' for articles")
    if kind == "social" and vals.get("platform") not in ("facebook", "instagram"):
        errors.append(f"platform must be facebook|instagram, got {vals.get('platform')!r}")
    if kind == "youtube":
        if vals.get("platform") != "youtube":
            errors.append("platform must be 'youtube'")
        dur = vals.get("duration", "").strip('"')
        if not re.match(r"^\d+:\d{2}(:\d{2})?$", dur):
            errors.append(f"duration must be filled mm:ss / h:mm:ss, got {dur!r}")

    # body skeleton
    if kind == "book":
        for marker, label in [("\n# ", "# Title H1"), ("**Synopsis:**", "**Synopsis:** block"),
                              ("## Recommendations", "## Recommendations section")]:
            if marker not in "\n" + body:
                errors.append(f"body missing {label}")
        if not vals.get("cover", "").strip('"'):
            warnings.append("cover is blank — allowed only if Open Library AND Google Books both fail")
        return errors, warnings

    h1s = re.findall(r"^# .+$", body, re.M)
    if not h1s:
        errors.append("body missing `# <title>` H1 heading")
    for sec in ("## Summary", "## Deep Dive", "## Source"):
        if not re.search(rf"^{re.escape(sec)}", body, re.M):
            errors.append(f"body missing `{sec}` section")
    if kind == "article":
        ft = re.split(r"^## Full Translation.*$", body, maxsplit=1, flags=re.M)
        if len(ft) < 2:
            warnings.append("article note missing `## Full Translation (TH)` cross-check section (required for captures from 2026-07-15 on)")
        else:
            # A summary parked under the translation heading is a fabrication. Catch the
            # disclaimer an agent writes when it abridges — but only an agent's own note
            # about the translation, not the source's prose ("กล่าวโดยย่อ" in an abstract,
            # "จึงสรุปได้ว่า" in a proof). Require BOTH: it sits in the opening block, and
            # it talks about the translation itself.
            opening = ft[1].lstrip()[:600]
            meta = ("การแปลนี้", "หมายเหตุ", "this translation", "translator's note")
            abridge = ("สรุป", "กระชับ", "โดยย่อ", "condensed", "abridged", "summariz")
            if any(m in opening for m in meta) and any(a in opening for a in abridge):
                errors.append("`## Full Translation` opens with a note saying it is condensed/summarized — a summary under this heading is a fabrication, not a translation. Translate the source in full, or stop and ask (see SKILL.md: sources over ~8k words)")

    # deep-dive sections between ## Deep Dive and ## My Notes / ## Source
    dd = re.split(r"^## Deep Dive.*$", body, maxsplit=1, flags=re.M)
    if len(dd) == 2:
        tail = re.split(r"^## (?:My Notes|Source).*$", dd[1], maxsplit=1, flags=re.M)[0]
        sections = re.findall(r"^## .+$", tail, re.M)
        nsec = len(sections)
        if nsec == 0:
            errors.append("no `## <topic>` sections found under ## Deep Dive")
        # Empty `###` subsections. A heading with nothing under it passes every other
        # check here and every check in audit_fidelity.py — the shape is perfect and
        # there is no claim to falsify — so an agent that writes only the skeleton gets
        # a clean bill of health for a note with no deep dive in it. Split on ANY
        # heading so a `###` trailed directly by the next `## topic` is still caught.
        chunks = re.split(r"^(#{2,} .+)$", tail, flags=re.M)
        hollow = []
        for i in range(1, len(chunks), 2):
            head = chunks[i].strip()
            if not head.startswith("### "):
                continue
            content = chunks[i + 1] if i + 1 < len(chunks) else ""
            if not content.strip(" \t\n-"):  # blank, or nothing but `---` separators
                hollow.append(head[4:].strip())
        if hollow:
            uniq = sorted(set(hollow))
            shown = ", ".join(repr(u) for u in uniq[:3]) + ("…" if len(uniq) > 3 else "")
            errors.append(
                f"{len(hollow)} empty `###` subsection(s) — heading present, no body under it "
                f"({shown}). The deep-dive body IS the note; a correct skeleton with nothing "
                f"in it is not a digest. Write the content or drop the heading."
            )
        # Topic headings must not mix languages inside one note (rule set 2026-09-12: a heading
        # follows the SOURCE's language — Thai video → Thai headings — and must say what is
        # interesting in that stretch). Which language is right depends on the source, which no
        # script can see; mixing inside a single note is always wrong, and that is checkable.
        if kind in ("youtube", "article", "social") and vals.get("captured", "").strip('"') >= "2026-09-12":
            heads = [h[3:].strip() for h in re.findall(r"^## .+$", tail, re.M)]
            th = en = 0
            for h in heads:
                letters = [c for c in h if c.isalpha()]
                if not letters:
                    continue
                # Any Thai word makes it a Thai heading. Majority-of-letters counted
                # "แกนที่ 5 Peace of Mind" as English, and the resulting error pushed an
                # agent to spell SME/IPO/Excel in Thai script (2026-09-19). English terms
                # inside a Thai heading are normal Thai usage; an all-English heading is not.
                if sum("฀" <= c <= "๿" for c in letters) >= 2:
                    th += 1
                else:
                    en += 1
            if th and en:
                errors.append(
                    f"deep-dive headings mix languages ({th} Thai, {en} all-English) — every topic heading "
                    f"follows the source's language (see prompts/step2_deepdive.md). In a Thai note, "
                    f"rewrite the all-English headings in Thai; English TERMS inside a Thai heading "
                    f"(SME, IPO, Put Options, MCP) are fine — keep them in English, never spell "
                    f"them in Thai script.")
        # The deep dive must be written in THAI. Quotes stay in the source language, but
        # `คอนเซปหลัก` and `Breakdown Idea & Examples` are the digest, and the skill asks for
        # Thai prose ("เล่าเหมือนเพื่อนเล่าให้ฟัง"). An English-source article digested by an
        # agent that was handed a bare skeleton drifts into English and still passes every
        # other check — two notes in the library did exactly that (2026-09-09, 2026-07-25).
        if kind in ("youtube", "article", "social") and vals.get("captured", "").strip('"') >= "2026-09-12":
            dd_body = "".join(
                m.group(1) for m in re.finditer(
                    r"^### (?:คอนเซปหลัก|Breakdown Idea & Examples)\s*$(.*?)(?=^###|\Z)",
                    tail, re.M | re.S))
            letters = [c for c in dd_body if c.isalpha()]
            if letters:
                thai = sum("฀" <= c <= "๿" for c in letters) / len(letters)
                if thai < 0.30:
                    errors.append(
                        f"deep-dive body is {thai:.0%} Thai — `คอนเซปหลัก` and `Breakdown Idea & "
                        f"Examples` must be written in Thai (only `Original Quotes` stay in the "
                        f"source language). See prompts/step2_deepdive.md")
        # Original Quotes must contain actual verbatim quote lines (`- "..."`), not
        # paraphrased tips. If there are Original-Quotes sections but not a single
        # `- "` quote line anywhere in the deep dive, the quotes were fabricated/omitted.
        # Warning (not error): legacy notes captured before the Original-Quotes rule often
        # have no verbatim quotes, so hard-failing them retroactively is too aggressive.
        # Real fabrication (a summary under Full Translation) is caught by its own ERROR.
        nqsec = len(re.findall(r"^### Original Quotes", tail, re.M))
        nquote = len(re.findall(r'^\s*[-*]\s+"', tail, re.M))
        if nqsec and nquote == 0:
            warnings.append(f"{nqsec} `### Original Quotes` section(s) but no `- \"…\"` verbatim quote lines — quotes must be real source lines, not paraphrased tips (legacy notes: backfill when revisited)")
        elif nqsec and nquote < nqsec:
            warnings.append(f"only {nquote} verbatim quote line(s) for {nqsec} Original-Quotes section(s) — each section should carry 1–3 real `- \"…\"` quotes")
        # summary bullet count vs section count (soft)
        sm = re.split(r"^## Summary.*$", body, maxsplit=1, flags=re.M)
        if len(sm) == 2:
            sm_block = re.split(r"^## ", sm[1], maxsplit=1, flags=re.M)[0]
            bullets = re.findall(r"^\s*[-*] ", sm_block, re.M)
            if bullets and nsec and nsec < len(bullets) - 1:
                warnings.append(f"only {nsec} deep-dive sections for {len(bullets)} summary bullets — should be ~1 per bullet")
            if kind == "youtube":
                stamped = [b for b in re.findall(r"^\s*[-*] .*$", sm_block, re.M) if re.search(r"\[\d{1,3}:\d{2}", b)]
                if len(stamped) < len(bullets):
                    errors.append(f"summary bullets missing [mm:ss] timestamps ({len(stamped)}/{len(bullets)} have one)")
            # Bullet count. The skill sets the count from the segment list, not a fixed number,
            # but two floors are mechanical: never fewer than 5, and a long conversation cannot
            # run one bullet per 6+ minutes without slicing by the clock instead of by topic.
            # Date-gated — a 1-bullet article and a 7-slice 64-min interview both passed on
            # 2026-09-11, but failing the whole backlog retroactively helps nobody.
            if vals.get("captured", "").strip('"') >= "2026-09-12":
                if len(bullets) < 5:
                    errors.append(f"only {len(bullets)} summary bullet(s) — a digest needs at least 5 "
                                  f"(the count follows your segment list; see SKILL.md step 3)")
                dur = vals.get("duration", "").strip('"')
                if kind == "youtube" and re.match(r"^\d+:\d{2}(:\d{2})?$", dur):
                    parts = [int(x) for x in dur.split(":")]
                    mins = parts[0] * 60 + parts[1] if len(parts) == 3 else parts[0]
                    if mins >= 30 and len(bullets) and len(bullets) < mins // 6:
                        errors.append(
                            f"{len(bullets)} summary bullets for a {mins}-minute video — one bullet per "
                            f"{mins / len(bullets):.0f} minutes. Walk the transcript and give each real "
                            f"topic shift its own bullet (~one per 3–5 min), never fixed-size slices")
        # A script-generated note (2026-09-26, 42 sections) passed every check above: verbatim
        # quotes, full coverage, no repeated paragraph — while no model had read the video.
        # These three catch its fingerprints; each is a sign the digest was never written.
        if vals.get("captured", "").strip('"') >= "2026-09-26":
            errors += template_fingerprints(tail, body)
        if kind == "youtube":
            nts = len(re.findall(r"^\*\*Timestamp:\*\*", tail, re.M))
            if nts < nsec:
                errors.append(f"each deep-dive section needs a **Timestamp:** block — found {nts} for {nsec} sections")
    return errors, warnings


def _ts(s):
    p = [int(x) for x in s.split(":")]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


def template_fingerprints(tail, body):
    errors = []
    sections = re.split(r"^## ", tail, flags=re.M)[1:]
    if len(sections) < 4:
        return errors
    heads = [s.split("\n", 1)[0].strip() for s in sections]

    masked = {re.sub(r"\d+", "#", h) for h in heads}
    if len(masked) < len(heads) * 0.8:
        errors.append(f"{len(heads)} `##` headings collapse to {len(masked)} once numbers are masked "
                      f"(e.g. {heads[0]!r}) — a heading must name that section's topic")
    sm = re.split(r"^## Summary.*$", body, maxsplit=1, flags=re.M)
    if len(sm) == 2:
        bl = re.findall(r"^\s*[-*] (.*)$", re.split(r"^## ", sm[1], maxsplit=1, flags=re.M)[0], re.M)
        mb = {re.sub(r"[\d:\[\]]+", "#", b).strip() for b in bl}
        if len(bl) >= 4 and len(mb) < len(bl) * 0.8:
            errors.append(f"{len(bl)} summary bullets collapse to {len(mb)} once numbers are masked — "
                          f"each bullet must say what that stretch is about")

    # Thai has no inter-word spaces, so a long space-free Thai run is roughly one clause.
    seen = {}
    for i, s in enumerate(sections):
        prose = re.split(r"^### Original Quotes", s, flags=re.M)[0]
        for run in set(re.findall(r"[฀-๿]{25,}", prose)):
            seen.setdefault(run, set()).add(i)
    rep = sorted(((len(v), k) for k, v in seen.items() if len(v) >= 4), reverse=True)
    if rep:
        errors.append(f"{len(rep)} Thai clause(s) repeat across 4+ sections, worst in {rep[0][0]} "
                      f"sections: {rep[0][1][:40]!r}… — this is filler, not a digest of what was said")

    spans = []
    for s in sections:
        m = re.search(r"^\*\*Timestamp:\*\*\s*\n\s*[-*] \[(\d{1,3}:\d{2}(?::\d{2})?)-(\d{1,3}:\d{2}(?::\d{2})?)\]",
                      s, re.M)
        if m:
            spans.append(_ts(m.group(2)) - _ts(m.group(1)))
    if len(spans) >= 8:
        mean = sum(spans) / len(spans)
        close = sum(abs(x - mean) <= mean * 0.05 for x in spans)
        if mean >= 120 and close >= len(spans) * 0.8:
            errors.append(f"{close}/{len(spans)} section ranges are ~{mean / 60:.1f} min long — the "
                          f"transcript was sliced by the clock, not by topic shift")
    return errors


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    if argv[1] == "--all":
        files = []
        for sub in ("youtube", "article", "social", "wishlist/Books"):
            files += sorted(p for p in (RESOURCES / sub).rglob("*.md")
                            if "_transcripts" not in p.parts)
    else:
        files = [Path(a) for a in argv[1:]]
    bad = 0
    for f in files:
        errors, warnings = check(f)
        if errors is None:  # transcript sibling / non-note — skip silently
            continue
        if errors:
            bad += 1
            print(f"FAIL {f}")
            for e in errors:
                print(f"  ERROR: {e}")
        for w in warnings:
            print(f"  warn ({f.name}): {w}")
        if not errors and not warnings:
            print(f"ok   {f.name}")
        elif not errors:
            print(f"ok   {f.name} (with warnings)")
    print(f"\n{len(files)} files checked, {bad} failing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
