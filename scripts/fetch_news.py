#!/usr/bin/env python3
"""Daily AI news digest: pull RSS feeds, dedupe, optionally summarize with Claude, write markdown."""
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = Path(os.getenv("FEEDS_FILE", ROOT / "feeds.yml"))
SEEN_FILE = ROOT / "data" / "seen.json"
NEWS_DIR = ROOT / "news"
README = ROOT / "README.md"

TZ = ZoneInfo(os.getenv("DIGEST_TZ", "America/New_York"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "30"))
SEEN_DAYS = 21
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ai-news-digest/1.0)"}


def clean(text, limit=260):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def entry_time(e):
    for key in ("published_parsed", "updated_parsed"):
        if e.get(key):
            return datetime(*e[key][:6], tzinfo=timezone.utc)
    return None


def fetch_all(config, seen, cutoff):
    items, errors = [], []
    for cat in config["categories"]:
        for f in cat["feeds"]:
            try:
                r = requests.get(f["url"], headers=HEADERS, timeout=20)
                r.raise_for_status()
                parsed = feedparser.parse(r.content)
            except Exception as ex:  # one dead feed shouldn't kill the run
                errors.append(f"{f['name']}: {ex}")
                continue
            count = 0
            for e in parsed.entries:
                link = e.get("link")
                if not link or link in seen:
                    continue
                t = entry_time(e)
                if t and t < cutoff:
                    continue
                items.append({
                    "category": cat["name"],
                    "source": f["name"],
                    "title": clean(e.get("title", "(untitled)"), 200),
                    "link": link,
                    "summary": clean(e.get("summary", "")),
                    "time": (t or datetime.now(timezone.utc)).isoformat(),
                })
                count += 1
                if count >= f.get("max", 8):
                    break
    return items, errors


def summarize(items):
    if not os.getenv("ANTHROPIC_API_KEY") or not items:
        return None
    try:
        import anthropic

        listing = "\n".join(
            f"- ({it['source']}) {it['title']} | {it['summary']} | {it['link']}" for it in items[:150]
        )
        prompt = (
            "You write a daily AI news briefing for an AI student and engineering intern who wants to "
            "know what's new, what changed, and what matters. Using ONLY the items below:\n\n"
            "## TL;DR\n3 to 5 bullets on the most important developments today.\n\n"
            "## Releases & Products\n## Research\n## Industry & Policy\n## Tools & Open Source\n"
            "Under each heading, one-sentence bullets that end with a markdown link to the source. "
            "Merge duplicate stories, skip fluff and listicles, omit empty sections, never invent facts.\n\n"
            f"ITEMS:\n{listing}"
        )
        msg = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=2500, messages=[{"role": "user", "content": prompt}]
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()
    except Exception as ex:
        print(f"Summary skipped: {ex}", file=sys.stderr)
        return None


def render(now, items, summary, errors, n_sources):
    lines = [
        f"# AI News: {now:%A, %B %-d, %Y}",
        f"_{len(items)} new items from {n_sources} sources · generated {now:%-I:%M %p %Z}_",
        "",
    ]
    if summary:
        lines += [summary, "", "---", ""]
    lines.append("## All Headlines")
    current = None
    for it in items:
        if it["category"] != current:
            current = it["category"]
            lines += ["", f"### {current}"]
        lines.append(f"- **[{it['title']}]({it['link']})** · {it['source']}")
        if it["summary"]:
            lines.append(f"  <br><sub>{it['summary']}</sub>")
    if not items:
        lines.append("_Quiet day, nothing new._")
    if errors:
        lines += ["", "<details><summary>Feeds that failed</summary>", ""]
        lines += [f"- {e}" for e in errors] + ["", "</details>"]
    return "\n".join(lines) + "\n"


def update_readme():
    files = sorted(NEWS_DIR.rglob("*.md"), reverse=True)[:14]
    links = "\n".join(f"- [{p.stem}]({p.relative_to(ROOT).as_posix()})" for p in files)
    block = f"<!-- LATEST:START -->\n{links}\n<!-- LATEST:END -->"
    text = README.read_text() if README.exists() else "# AI News Digest\n\n" + block + "\n"
    text = re.sub(r"<!-- LATEST:START -->.*<!-- LATEST:END -->", block, text, flags=re.S)
    README.write_text(text)


def main():
    config = yaml.safe_load(FEEDS_FILE.read_text())
    now_utc = datetime.now(timezone.utc)
    now = now_utc.astimezone(TZ)

    seen = json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else {}
    items, errors = fetch_all(config, seen, now_utc - timedelta(hours=LOOKBACK_HOURS))
    order = [c["name"] for c in config["categories"]]
    # newest first within each category, categories in feeds.yml order
    items.sort(key=lambda it: it["time"], reverse=True)
    items.sort(key=lambda it: order.index(it["category"]))

    summary = summarize(items)
    n_sources = sum(len(c["feeds"]) for c in config["categories"]) - len(errors)

    out = NEWS_DIR / f"{now:%Y}" / f"{now:%m}" / f"{now:%Y-%m-%d}.md"
    if out.exists() and not items:
        print("No new items; keeping today's existing digest.")
        return
    if out.exists():  # same-day rerun: save as a second edition instead of overwriting
        out = out.with_name(f"{now:%Y-%m-%d}-{now:%H%M}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(now, items, summary, errors, n_sources))

    today = now_utc.date().isoformat()
    seen.update({it["link"]: today for it in items})
    keep_after = (now_utc - timedelta(days=SEEN_DAYS)).date().isoformat()
    seen = {k: v for k, v in seen.items() if v >= keep_after}
    SEEN_FILE.parent.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, indent=0, sort_keys=True))

    update_readme()
    print(f"Wrote {out.relative_to(ROOT)}: {len(items)} items, {len(errors)} feed errors, "
          f"summary={'yes' if summary else 'no'}")


if __name__ == "__main__":
    main()
