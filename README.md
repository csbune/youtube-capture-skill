# youtube-capture — a Claude Code skill

Turn any YouTube video into an Obsidian note: a timestamped bullet summary plus a Thai deep-dive
with verbatim quotes. Two scripts then check the note against the real transcript, so fake quotes,
wrong timestamps, and skipped sections all fail the check.

## Install

Requires [Claude Code](https://claude.com/claude-code), Python 3.10+, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/csbune/youtube-capture-skill.git
cd youtube-capture-skill
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

**Antigravity / Codex:** open this folder and say "run the youtube-capture skill on <url> #thinking".
The skill is also exposed at `.agents/skills/`, and `AGENTS.md` points agents to it.

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
