#!/usr/bin/env python3
"""
fetch_transcript.py — Fetch YouTube transcript + metadata.

Dependencies (installed via uv):
    youtube-transcript-api
    yt-dlp

Usage:
    python fetch_transcript.py <youtube-url-or-id> --transcript <out.txt> --metadata <out.json>
    python fetch_transcript.py <youtube-url-or-id> --transcript -   # stdout

Transcript output: timestamped plain text  [MM:SS] line
Metadata output: JSON with title, channel, description, duration, publish_date, thumbnail
"""

import argparse
import json
import re
import subprocess
import sys


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_video_id(url_or_id: str) -> str:
    """Extract the 11-char video ID from a YouTube URL or return as-is."""
    patterns = [
        r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})',
        r'^([A-Za-z0-9_-]{11})$',
    ]
    for pat in patterns:
        m = re.search(pat, url_or_id)
        if m:
            return m.group(1)
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def build_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# ── Transcript ─────────────────────────────────────────────────────────────────

def fetch_transcript(video_id: str) -> tuple[list[dict], str]:
    """
    Fetch transcript via youtube-transcript-api.
    Returns (segments, language_code).
    Tries: Thai → English → any available.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    last_error = None

    # Priority order: Thai, English, then whatever is available
    for lang in ['th', 'en']:
        try:
            segments = api.fetch(video_id, languages=[lang])
            return segments, lang
        except Exception as e:
            last_error = e
            continue

    # Fallback: try to get any available transcript
    try:
        transcript_list = api.list(video_id)
        for t in transcript_list:
            try:
                segments = t.fetch()
                return segments, t.language_code
            except Exception as e:
                last_error = e
                continue
    except Exception as e:
        last_error = e

    # Report WHY. "No transcript available" hid an IP block for a whole day on
    # 2026-09-17 and sent the agent hunting for a missing-captions bug instead.
    if last_error is not None:
        raise RuntimeError(
            f"Could not fetch transcript for {video_id}: "
            f"{type(last_error).__name__}: {str(last_error).strip().splitlines()[0]}"
        ) from last_error
    raise RuntimeError(f"No transcript available for video: {video_id}")


def format_transcript(segments, include_timestamps: bool = True) -> str:
    """Format transcript segments as timestamped plain text."""
    lines = []
    for s in segments:
        mins = int(s.start // 60)
        secs = int(s.start % 60)
        text = s.text.strip().replace('\n', ' ')
        if text:
            if include_timestamps:
                lines.append(f"[{mins:02d}:{secs:02d}] {text}")
            else:
                lines.append(text)
    return '\n'.join(lines)


# ── Metadata ───────────────────────────────────────────────────────────────────

def fetch_metadata(url: str) -> dict:
    """
    Fetch video metadata via yt-dlp --dump-json.
    No API key required. Returns a clean subset of fields.
    """
    try:
        result = subprocess.run(
            ['yt-dlp', '--dump-json', '--skip-download', '--no-warnings', url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {result.stderr.strip()}")

        raw = json.loads(result.stdout)

        # Extract clean metadata
        return {
            'title': raw.get('title', ''),
            'channel': raw.get('channel', raw.get('uploader', '')),
            'channel_url': raw.get('channel_url', raw.get('uploader_url', '')),
            'description': raw.get('description', ''),
            'duration': raw.get('duration', 0),
            'duration_string': raw.get('duration_string', ''),
            'upload_date': raw.get('upload_date', ''),  # YYYYMMDD
            'view_count': raw.get('view_count', 0),
            'like_count': raw.get('like_count', 0),
            'thumbnail': raw.get('thumbnail', ''),
            'tags': raw.get('tags', []),
            'categories': raw.get('categories', []),
            'language': raw.get('language', ''),
        }

    except FileNotFoundError:
        # yt-dlp not installed — fall back to oEmbed for basic metadata
        return fetch_metadata_oembed(url)
    except Exception as e:
        print(f"Warning: yt-dlp metadata failed ({e}), trying oEmbed fallback", file=sys.stderr)
        return fetch_metadata_oembed(url)


def fetch_metadata_oembed(url: str) -> dict:
    """Fallback: basic metadata via YouTube oEmbed (no deps, no key)."""
    import urllib.request
    import urllib.parse

    oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url, safe='')}&format=json"
    try:
        with urllib.request.urlopen(oembed_url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return {
            'title': data.get('title', ''),
            'channel': data.get('author_name', ''),
            'channel_url': data.get('author_url', ''),
            'description': '',
            'duration': 0,
            'duration_string': '',
            'upload_date': '',
            'view_count': 0,
            'like_count': 0,
            'thumbnail': data.get('thumbnail_url', ''),
            'tags': [],
            'categories': [],
            'language': '',
        }
    except Exception as e:
        print(f"Warning: oEmbed fallback also failed: {e}", file=sys.stderr)
        return {
            'title': '', 'channel': '', 'channel_url': '', 'description': '',
            'duration': 0, 'duration_string': '', 'upload_date': '',
            'view_count': 0, 'like_count': 0, 'thumbnail': '',
            'tags': [], 'categories': [], 'language': '',
        }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Fetch YouTube transcript + metadata')
    parser.add_argument('url', help='YouTube URL or video ID')
    parser.add_argument('--transcript', '-t', default='-',
                        help='Output path for transcript (default: stdout, use - for stdout)')
    parser.add_argument('--metadata', '-m', default=None,
                        help='Output path for metadata JSON (default: skip)')
    parser.add_argument('--no-timestamps', action='store_true',
                        help='Omit timestamps from transcript')

    args = parser.parse_args()

    # Extract video ID
    video_id = extract_video_id(args.url)
    url = build_url(video_id)
    print(f"▶ Video ID: {video_id}", file=sys.stderr)

    # Fetch transcript
    print(f"▶ Fetching transcript...", file=sys.stderr)
    segments, lang = fetch_transcript(video_id)
    transcript_text = format_transcript(segments, include_timestamps=not args.no_timestamps)
    print(f"▶ Transcript: {lang}, {len(segments)} segments, {len(transcript_text):,} chars", file=sys.stderr)

    # Write transcript
    if args.transcript == '-':
        print(transcript_text)
    else:
        with open(args.transcript, 'w', encoding='utf-8') as f:
            f.write(transcript_text)
        print(f"▶ Transcript written to: {args.transcript}", file=sys.stderr)

    # Fetch & write metadata
    if args.metadata:
        print(f"▶ Fetching metadata...", file=sys.stderr)
        meta = fetch_metadata(url)
        meta['video_id'] = video_id
        meta['url'] = url
        meta['transcript_language'] = lang
        meta['transcript_segments'] = len(segments)
        meta['transcript_chars'] = len(transcript_text)

        with open(args.metadata, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"▶ Metadata written to: {args.metadata}", file=sys.stderr)


if __name__ == '__main__':
    main()
