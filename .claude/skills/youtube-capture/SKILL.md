---
name: youtube-capture
description: Agentically fetch a YouTube video's transcript, write a Step-1 bullet summary + Step-2 Thai deep-dive, and save an Obsidian note to inbox/resources/youtube/ with a fixed frontmatter (type = thinking|building, 3 connecting concept tags).
---

# YouTube Capture (Agentic Workflow)

You act as the orchestrator + summarizer: fetch the transcript, digest it, and save a consistently-formatted Obsidian note. Do NOT ask permission before running the fetch script.

> 🔴 **Delegating the digest to a subagent?** Give it the path to THIS file and have it read the whole file first. Your prompt adds **inputs only** (URL, type tag, slug, transcript/metadata paths, the user's note) — never a restated or shortened version of these rules, never "skip the scripts". Then run step 6 yourself before reporting.

## Flow

### 1. Read the input
- Find the **YouTube URL(s)** in the user's message.
- Read the **content type** the user appends as `#thinking` or `#building` (e.g. `/youtube-capture <url> #thinking`):
  - **thinking** = something to *think* about — a plan, an idea, reflection.
  - **building** = something to *do* — a knowledge ref, a tool, an example/project to re-engineer and build.
  - This becomes the `type:` field. If no `#` is given, ask which one before saving.

### 1b. 🔴 Queue the URL — this is also the duplicate check
**Write the URL with your file-writing tool** (not a shell command) to:
```
inbox/engine/queue/<video_id>.url        one URL, one line
```
`<video_id>` = the 11-char id from the URL (`...watch?v=SSC-23pIXrw` → `SSC-23pIXrw.url`). Queue every URL the user gave you, one file each, before fetching anything.

The duplicate check then runs inside step 2, **before a single byte is downloaded**. It prints `ALREADY CAPTURED` and skips that video. **That means STOP for it — do not summarize, do not write a second note.**

Why a re-paste is not a mistake: **The user re-pasting a URL means they have not consumed that note yet.** The note is not stale — their queue is. So the task changes from "capture this" to "move the existing note to the front of the queue":
```
python3 inbox/engine/scripts/check_url.py "<URL>" --redate
```
That rewrites `captured:`, renames the `yymmdd-` prefix to today, renames the sibling transcript, and repoints every `[[wikilink]]`. Then report which note was re-dated and **stop** — the digest already exists.

Only re-digest if the user explicitly says the existing note is wrong or incomplete; then edit that note in place, never create a sibling.

### 2. Fetch transcript + metadata — ONE command, never varies
```
python3 inbox/engine/scripts/capture_queue.py fetch
```
**Run it exactly as written — no URL, no flags, no timestamps, nothing appended, no `sleep … &&` in front.** You approve this string once and never sees the popup again; adding anything makes it a new command to the IDE's approval system and the popups come back (2026-09-17).

**It blocks until your video is ready.** If another agent is already fetching, it waits for that run, then processes what's left, then prints every ready video id. Do not poll, re-run, sleep, `ls work/`, or touch `work/.lock`, and **never end your turn "waiting for fetch"** — a sub-agent that does never comes back (2026-09-19: two videos fetched, never written).

**The only shell commands in this whole skill are the `capture_queue.py` ones.** Read transcripts with your file-read/search tools — no `grep`/`awk`/`cat`, no helper scripts, no `python3 -c`.

It walks the queue one video at a time under a lock, and writes per-video:
```
inbox/engine/work/<video_id>/transcript.txt
inbox/engine/work/<video_id>/metadata.json
```
Read those two. **Pull `duration_string` from the metadata and fill the `duration` field — never leave it blank.** Also take title, channel, upload date.

**Why one command instead of one per video:** ten parallel fetches got the IP blocked by YouTube (HTTP 429) and, with a shared `/tmp` filename, mixed two videos' transcripts into one note on 2026-09-17. Sequential + per-video-id paths remove both. If it stops on a block, **everything stays queued** — run the same command again in a few hours and it resumes. Never work around a block by fetching some other way.

It also runs **both** duplicate checks for you: the URL check before downloading, and, once metadata is in, the **re-upload** check a URL cannot see — the same episode posted under a new video id (*real case: Ookbee "Pain Point EP.1" as both `kY7iQWJc1hE` and `nsaFIEKQkYE`, same 1:07:16 runtime*). If it reports either, STOP for that video and ask the user whether to re-date the existing note — do not decide alone, do not write a second note.

**Title vs. filename — they are different on purpose:**
- **`title:` frontmatter (and the `# heading`) = the ORIGINAL video title, VERBATIM.** Never reword, translate, shorten, or strip it — keep `| EP.xx`, `#hashtags`, channel suffixes exactly as YouTube shows. This is what the user recognizes and remembers what hooked them.
- **Filename SLUG = a cleaned, short form** of the title (Thai title → short Thai slug; English title → English slug). Strip the clutter (`| Show EP.xx`, `#hashtags`, `@channel`, `[x/y]`) **from the slug only — not from the title.**

### 3. Digest (your job)

For a very long (> 90 min) or course-style video, tell the user a single digest will lose detail and ask whether to proceed.

Follow the prompt rules in:
- `inbox/engine/prompts/step1_summary.md` — Step 1: bullet summary, each bullet starting with `[mm:ss]` timestamps; plus the Glasp insight search. **Bullet count = your segment list** (see Coverage below) — one bullet per distinct topic, not a fixed number. Guide: a video under ~30 min usually has 5–10; a longer conversation has one per real topic shift, roughly one every 3–5 min (a 64-min interview ≈ 13–20). Never fewer than 5. **Never slice by the clock** — a boundary goes where the topic changes, not every N minutes (a 64-min interview cut into seven 9-minute blocks is the failure this rule exists for).
- `inbox/engine/prompts/step2_deepdive.md` — Step 2: Thai deep-dive per topic.
Format rules: Thai hook = exactly 1 sentence (สั้น กระชับ น่าสนใจ); Timestamps block at the top of each section `[xx:xx-xx:xx]`; Actionable Tips = numbered list with bold keywords. **Voice: เล่าเหมือนเพื่อนเล่าให้ฟัง — storytelling with anecdotes and depth, not a dry lecture summary.** Use only what's in the transcript.
- **Granularity: one deep-dive section per summary bullet** — keep it detailed topic-by-topic; do NOT compress 8 bullets into 2-3 sections. **Separate every topic section with a `---` line.**
- 🔴 **Every `###` subsection must carry a body. `คอนเซปหลัก` and `Breakdown Idea & Examples` are the digest** — `คอนเซปหลัก` = the idea in 2–5 sentences of Thai; `Breakdown Idea & Examples` = the speaker's own story/example that makes it land. Writing the headings and leaving them blank produces a note that passes BOTH validators (perfect shape, no claim to falsify) and contains nothing. `validate_note.py` now hard-fails an empty `###` — but the point is to write the content, not to satisfy the check.

**Coverage (read the WHOLE video, not just the parts that summarize easily):**
- **Walk the transcript start → end and list every distinct segment BEFORE writing.** Every segment must land inside some section's `**Timestamp:**` range. Target **≥90% of the runtime covered** by the union of those ranges; any hole longer than ~30s means you dropped something — go back and read what was in it.
- **Every voice that is not the narrator gets its own treatment.** Archival clips, interview cut-ins, a poem or a song read aloud, a co-host, an audience question, a customer story. These are exactly what a narrator-following summarizer deletes silently, and they are usually the *evidence* the narration is built on. **If the video is about someone (`idea owner:`), a digest carrying only the narrator's voice has lost the subject.** When such a segment runs ~30s+ or carries the emotional core, give it **its own `##` section** — and its own summary bullet, so the 1:1 rule still holds.
- **Keep the deliberate contradiction.** Creators stage tensions on purpose: an epitaph vs. a poem, a rule vs. its exception, a claim vs. the counter-clip. Keeping one half and dropping the other doesn't shorten the video, it inverts it. If two segments disagree, **both stay**.
- *(Real failure this rule exists for: a Mark Manson video on Bukowski where the digest kept every line of narration and dropped all four Bukowski clips — including the poem "If you're gonna try, go all the way", which is the exact counterweight to the "Don't try" epitaph the whole video is named after. 37% of runtime covered; the point of the video was gone.)*

**Source fidelity (NON-NEGOTIABLE — the transcript is ground truth, and it is saved beside the note so every claim is checkable):**
- **No invented advice.** Every Actionable Tip MUST trace to something the speaker actually says in the transcript. The most common failure is inventing tips the video never gave — do NOT extrapolate your own advice. If the segment states a principle but no concrete instruction, translate/quote the principle; don't manufacture a "tip" around it.
  - **Tips are optional per section, and each one carries its source line.** Write a tip only where the speaker gives an instruction or an actionable principle, and **end it with the `[mm:ss]` of the line that says it** — inside the section's Timestamp range, same rule as a quote. A section where the speaker gives no advice has **no** `**Actionable Tips:**` block; delete it rather than fill it. A template slot is not a reason to write advice. *(Real failure: a 64-min interview whose speaker gave one explicit piece of advice ([60:46] "creators should balance their lives") got 17 invented tips — and that one real tip was dropped.)*
- **No invented anecdotes, examples, numbers, names, or quotes.** If it isn't in the transcript, it doesn't go in the note. `Original Quotes` must be real lines from the transcript, not paraphrases dressed as quotes. **When the speaker gives an example, use THEIR example** — never swap in a more relatable one of your own (a digest that illustrated "I'm trying…" with *"ฉันกำลังพยายามลดน้ำหนัก"* when the speaker actually said *"I'm trying to work on this, or I'm trying to be more like that"* is a defect, not a translation choice).
- **Original Quotes — pull the speaker's real words, verbatim.** For each deep-dive section, quote **1–3 lines (more only if truly warranted)** taken from within that section's timestamp range. Choose by importance, not volume — enough to let the reader hear the speaker's actual voice and to sharpen the context, never a wall of quotes. **Copy word-for-word: do not reword, clean up, or translate the quote** — for some points the exact phrasing / word choice the speaker used is itself what carries the meaning and weight. Append `[mm:ss]` to each quote so it's checkable against `_transcripts/<slug>.md`. If a section has no genuinely sharp line, take what's there — never manufacture a sentence and pass it off as a quote.
- 🔴 **How `audit_fidelity.py` actually compares a quote — read this before writing any quote.** It strips the `[mm:ss]` prefix from every transcript line, joins the lines **with a single space**, and collapses whitespace. Three consequences, each of which has already cost a full re-digest:
  - **A quote that spans a line break needs the seam space.** Thai transcripts wrap mid-word, so the line `...ห้ามเขียนห้าม` + `ฟังเพลง` flattens to `...ห้ามเขียนห้าม ฟังเพลง` — **with** the space. Write the quote the way the flattened transcript reads, space included. Omitting it fails as "not verbatim" even though the characters look right on screen. *(Real failure: 31 of 37 Thai quotes in one note failed for exactly this.)*
  - **`>>` speaker markers survive flattening.** The prefix strip removes the timestamp, not the `>>`. So a quote that crosses from one speaker's turn into the next contains a literal `>>` in the transcript and can never match. **Quote inside one speaker turn.**
  - 🔴 **Never stitch fragments together with `...` and present it as one quote.** Joining two passages the speaker said minutes apart manufactures a sentence they never uttered — it reads as fluent quotation and is the single hardest fabrication to spot by eye, because every word in it is real. If two passages both matter, write **two quotes with their own `[mm:ss]`**. An ellipsis is only ever legitimate *inside* one contiguous passage, to drop a stumble. *(Found in the audit: dozens of `...`-stitched quotes across the library, some with a half that is in no transcript line at all.)*
  - **Do not paste transcript lines with their `[mm:ss]` prefixes inside the quoted text.** The flattener strips those markers, so a quote carrying them can never match. Strip them and keep the words. *(Real failure: all 19 quotes in one note were pasted raw, markers included — every one failed as "not verbatim" although the words were exactly right.)*
  - **Every `[mm:ss]` you cite must be a real line in the transcript** — both Timestamp-range boundaries and quote citations. Do NOT round, guess, or reconstruct one from the runtime: `grep` the transcript and copy a timestamp that is actually printed there. *(Recurring failure: `[31:00]` when the transcript's line is `[31:01]`; `[61:45]` when it is `[61:05]`.)*
- **Timestamp discipline = the audit hook.** Every deep-dive section's `**Timestamp:**` sub-bullets, every anecdote, and every Actionable Tip must correspond to a real `[mm:ss]` range in the transcript. Because the raw transcript is saved to `_transcripts/<slug>.md`, a reviewer can jump to any timestamp and confirm the claim is real — so a fabricated tip or a wrong timestamp is a hard defect, not a style nit. When in doubt, cite the timestamp and stay literal.
  - **The declared range must match what the section actually discusses.** Declaring `[04:36-04:54]` and then telling a story from `[04:03]` breaks the hook — the reviewer jumps there and finds nothing. **Move the story into the range, or fix the range to the section you actually wrote — never widen a range just to swallow a stray citation** (R4: widening while content stays missing is the one way to make the audit worthless). Never leave them out of sync.
- 🔴 **Never write ABOUT the timestamp — write what was SAID.** Lines like *"แนวคิดหลักในช่วง 05:20 คือ…"*, *"ตัวอย่างที่น่าสนใจในนาทีที่ 12:05…"*, *"คำอธิบายช่วงเวลานี้"* are filler: with the numbers masked they are the same sentence in every section, and `check` fails them as one repeated paragraph (2026-09-20: 5 notes). Never pad a section by repeating a sentence twice either — that fails too.
- **Write each section's range as its own bullet** — `**Timestamp:**` then `* [mm:ss-mm:ss] …` on the next line. An inline `**Timestamp:** [00:02-05:07]` parses as NO range, which used to exempt the section from every coverage and quote check; `check` now fails that instead.
- **A section whose range runs 10+ minutes must cite a `[mm:ss]` (quote or tip) from EACH half of that range.** If the second half is a different topic, it is a different section. *(2026-09-19: a section claimed [78:19-94:37] and quoted only 93:28 — 14 minutes of other topics hidden behind a widened range.)* `check` fails it and prints the skipped stretch.
- **Coverage self-audit before saving:** re-check that (a) every summary bullet has a deep-dive section, (b) no Actionable Tip lacks a transcript source, (c) every non-narrator segment got a section, (d) the union of Timestamp ranges covers ≥90% of the runtime with no >30s hole. Fix gaps before validating — step 6 runs a script that checks (a) and (d) mechanically.

### 4. Pick the 3 concept tags
Choose **exactly 3** `tags` — lowercase kebab-case concepts that name the video's core, *reusable* themes (e.g. `business-strategy`, `focus`, `monopoly`). Pick connectors, not hyper-specific phrases: they should be general enough to recur on other notes so the graph view links related captures across the library. These are separate from `type`. **NEVER put `thinking` or `building` into `tags:` — the `#thinking`/`#building` token from the input goes ONLY in `type:`. `tags: [thinking]` is always wrong.**

### 5. Assemble & save
- **Body** follows `inbox/engine/templates/obsidian_note.md`. Order: Summary → Deep Dive → My Notes (if any) → Source.
- **REQUIRED body skeleton — the saved file MUST match this shape exactly. Do NOT improvise a layout, even if you did not open the template file:**
  ```markdown
  # <ORIGINAL video title, verbatim>

  > **Channel**: <channel> · **Duration**: <mm:ss>
  > **URL**: <url>

  ---

  ## Summary

  * [mm:ss] <bullet — one per distinct topic segment; the count follows your segment list (≥5; long conversations ≈ one per 3–5 min)>

  Learn more on Glasp: https://glasp.co/reader?url=<url>

  ---

  ## Deep Dive

  ## <Topic heading — ONE `##` section per summary bullet · SAME LANGUAGE AS THE SOURCE (Thai video → Thai heading) · must name what is actually interesting in that stretch, so the outline alone tells the reader which topic to pick up later — never "Introduction" / "บทนำ" / "Key Ideas">
  <Thai hook — exactly 1 sentence>

  **Timestamp:**
  * [xx:xx-xx:xx] <short description>

  ### คอนเซปหลัก
  ### Breakdown Idea & Examples
  ### Original Quotes & Actionable Tips
  - "<verbatim line from the transcript, within this section's timestamp range>" [mm:ss]
  - "<1–3 such quotes total, chosen by importance>" [mm:ss]

  **Actionable Tips:**        ← ONLY if the speaker gives advice inside this range; otherwise omit the block
  1. **<keyword>:** <the speaker's own advice, in Thai> [mm:ss]

  ---
  (…repeat the `## topic` block, separated by `---`…)

  ## My Notes        ← ONLY if the user gave a note

  ---

  ## Source

  - 🎬 [Watch on YouTube](<url>)
  - 📖 [Read on Glasp](https://glasp.co/reader?url=<url>)
  - 📄 Transcript (cross-check): [[_transcripts/<slug>|full transcript with timestamps]]
  ```
  The `# title` H1, `## Summary`, `## Deep Dive`, a `**Timestamp:**` block in EVERY topic section, and `## Source` are all mandatory — a note missing any of them is broken.
- **The note ENDS at `## Source`. NEVER paste the raw transcript into the note itself.** A transcript inline bloats the note from ~30KB to 300KB+, wrecks it as LLM-loadable memory (loaders burn context on text the digest already covers), and pushes `## Source` out of its required last position. Collapsing/commenting it inside the note does NOT help — context cost is the bytes on disk, not what's visually hidden.
- **Save the transcript as a sibling file for cross-check — ONE command, never varies:**
  ```
  python3 inbox/engine/scripts/capture_queue.py file
  ```
  Run it after the note is saved. It finds the note carrying each fetched video's URL, writes the transcript verbatim (with its `[mm:ss]` lines) to `inbox/resources/youtube/_transcripts/<the note's slug>.md` with the cross-check header, and clears `work/`. **Do not copy the transcript through your own context** — it is 100–300KB, and hand-copying is how content from one video ended up in another video's file. Then link it from the note's `## Source` block as shown above. The validator skips `_transcripts/` automatically. This keeps the digest lean AND preserves ground truth for timestamp-level verification — fetched once, never lost, no re-fetch needed.
  - If it says *"no note carries this URL yet"*, the note's `url:` doesn't match what was fetched — fix the note, then run the same command again.
  - If a note is later **renamed**, its transcript sibling does not auto-rename — rename the transcript to the new slug and fix the two backlinks (the note's `## Source` link → transcript, and the transcript header's `[[note]]` backlink) so the pair stays matched.
- **`## My Notes`** (only if the user added a note, after Deep Dive, before Source): the user's note **verbatim** (their own thinking, kept out of the source-only Deep Dive), then a `**Related:**` line with **verified** `[[wikilinks]]` to related notes in `inbox/resources/…` (search by topic, esp. on "related/relate"; verify the file exists — never invent a link).
- **Frontmatter — the 9 required keys in this exact order, then optional keys. Do NOT drop/reorder the required 9 or add unknown keys (no `date`, `video_id`):**
  ```yaml
  ---
  title: "<the ORIGINAL video title, VERBATIM — never reworded/translated/stripped>"
  url: "<youtube url>"
  channel: "<channel name>"
  platform: youtube
  type: <thinking | building>
  captured: <YYYY-MM-DD>
  status: captured
  duration: "<mm:ss>"
  tags: [<concept-1>, <concept-2>, <concept-3>]
  idea owner: [<idea owner>]        # OPTIONAL — see below; omit if none
  expressed_as: "[[note]]"      # OPTIONAL — see below; omit unless status: expressed
  ---
  ```
  - `type` = one scalar value (`thinking` | `building`) — NOT a YAML list.
  - `channel` = **who published it** = the YouTube channel name.
  - `idea owner` = **the thinker** — the thinker whose framework/ideas the video presents, even if they are only cited and not speaking (e.g. a Mission-To-The-Moon video *about* Ray Dalio → `creator: Mission To The Moon`, `author: [Ray Dalio]`). May list several. **Optional** — omit when there's no single idea owner. `channel` ≠ `idea owner`.
  - `status` = one of **`captured`** (done), **`drafted`** (a draft/composed note exists — link it in `expressed_as`), **`expressed`** (worked up into a finished note). Nothing else.
  - `expressed_as` = a `[[wikilink]]` to the composed/finished note; add it when `status: expressed`.
  - `tags` = the 3 concept tags from step 4. **Write** them inline `[a, b, c]`. (Obsidian may later normalize to its native block-list form — one `- tag` per line — on open; that's fine, the validator accepts it. Don't "fix" it back.)
  - `duration` = the real `mm:ss` from metadata — never blank.
- Save to `inbox/resources/youtube/YYMMDD-slug.md` — **`YYMMDD` is TODAY, the capture date, same as `captured:` — never the video's upload date** (2026-09-19: two notes were filed as `260212-` and `260918-`; `validate_note.py` now fails that). **The slug is a cleaned, short form of the title** (Thai title → short Thai slug; English title → English slug), with clutter (`ep`, `|`, `#`, `@channel`, `[x/y]`) stripped **from the filename only** (the `title:` stays the original). You may save into a topic subfolder (e.g. `.../youtube/garyvee/`) — the libraries still pick it up.

### 6. Validate (MANDATORY — do not skip) — ONE command, never varies
```
python3 inbox/engine/scripts/capture_queue.py check
```
Run it **after** step 5's `file` command, so the transcript is in place. It runs BOTH gates — `validate_note.py` (shape) and `audit_fidelity.py` (the note against its transcript) — over every capture note touched in the last 24h, and prints `✓` per note or the failures. Re-run until every note shows `✓`. Never present a note that still fails.

**Never check your own quotes with a one-off `python3 -c "..."` or a hand-written grep pattern.** Those commands are unique every time, so each one costs the user an approval popup, and they check what you *think* you wrote. Use your own file-reading/search tools to look at the transcript, and let this command be the judge.

`audit_fidelity.py`, inside it, fails on: a quote that isn't verbatim in the transcript, an empty/near-empty quote, a `[mm:ss]` that doesn't exist, **a quote whose `[mm:ss]` falls outside the Timestamp range its own section declares**, summary bullets ≠ deep-dive sections, and any stretch of runtime the digest dropped (>30s hole, or <90% coverage). Re-run until it prints `clean`.
**On an out-of-range quote the fix is to quote from inside the range, or to move the quote to the section that really covers it — never to widen the range.** A section may declare several ranges; the quote need only land in one of them.
**Treat an uncovered stretch as an instruction to go read it** — the fix is to add the missing section, never to widen a Timestamp range to paper over the gap. Widening a range so the number goes green while the content stays missing is the one way to make this audit worthless.

### 7. Present & log
- Give the user a clickable link to the saved `.md`.
