# AI News Digest

A daily briefing on what's new in AI, committed here every morning by a GitHub Action.
Each day's file has a Claude-written TL;DR plus every headline, grouped by source type.

## Latest
<!-- LATEST:START -->
_First digest will appear after the workflow runs._
<!-- LATEST:END -->

## How It Works
- `.github/workflows/daily-ai-news.yml` runs daily (and on demand from the Actions tab)
- `scripts/fetch_news.py` pulls the feeds in `feeds.yml`, skips anything already seen, and writes `news/YYYY/MM/YYYY-MM-DD.md`
- If the `ANTHROPIC_API_KEY` secret is set, Claude writes the summary at the top; otherwise you get headlines only
- Edit `feeds.yml` to add or drop sources
