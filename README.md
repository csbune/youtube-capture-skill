# youtube-capture — a Claude Code skill

Turn any YouTube video into an Obsidian note: a timestamped bullet summary plus a Thai deep-dive
with verbatim quotes. Two scripts then check the note against the real transcript, so fake quotes,
wrong timestamps, and skipped sections all fail the check.

## Install

Requires [Claude Code](https://claude.com/claude-code), Python 3.10+, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/<OWNER>/youtube-capture.git
cd youtube-capture
claude
```

Use this folder as your Obsidian vault, or copy `inbox/` and `.claude/` into an existing vault root.
Python dependencies install automatically on the first fetch (via `uv`).

## Use

Inside Claude Code, from the vault root:

```
/youtube-capture https://www.youtube.com/watch?v=... #thinking
```

`#thinking` = ideas to reflect on · `#building` = something to do or build.

The note lands in `inbox/resources/youtube/YYMMDD-slug.md`, with the full transcript beside it in `_transcripts/`.

## Layout

```
.claude/skills/youtube-capture/SKILL.md   the skill (the instructions Claude follows)
inbox/engine/scripts/                     fetch queue, duplicate check, validators
inbox/engine/prompts/                     summary + deep-dive rules
inbox/engine/templates/                   note template + a worked example
inbox/resources/youtube/                  your notes go here
```

If YouTube rate-limits you (HTTP 429), the URLs stay queued. Run the skill again a few hours later.
