#!/usr/bin/env python3
"""Build the profile's token-free contribution data and animated SVG assets."""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import date
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

USERNAME = "Ihthos"
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "contributions.json"
CONTRIBUTIONS_URL = f"https://github.com/users/{USERNAME}/contributions"
API_URL = "https://api.github.com"
PALETTE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353", "#69f0a0"]
LANGUAGE_COLORS = {
    "C": "#555555", "C++": "#f34b7d", "CSS": "#663399", "Cuda": "#3A4E3A",
    "HTML": "#e34c26", "JavaScript": "#f1e05a", "Python": "#3572A5", "Shell": "#89e051",
    "TypeScript": "#3178c6", "CMake": "#DA3434", "Nix": "#7e7eff", "Dockerfile": "#384d54",
}


class CalendarParser(HTMLParser):
    """Extract contribution cells and their accessible tooltip counts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.days: list[dict[str, object]] = []
        self.day: dict[str, object] | None = None
        self.tooltip_for: str | None = None
        self.tooltip_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "td" and values.get("data-date"):
            self.day = {"date": values["data-date"], "level": int(values.get("data-level") or 0), "count": 0, "id": values.get("id")}
        elif tag == "tool-tip" and values.get("for"):
            self.tooltip_for = values["for"]
            self.tooltip_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.day is not None:
            self.days.append(self.day)
            self.day = None
        elif tag == "tool-tip" and self.tooltip_for:
            text = " ".join("".join(self.tooltip_text).split())
            match = re.search(r"([\d,]+) contributions?", text)
            count = int(match.group(1).replace(",", "")) if match else 0
            for day in self.days:
                if day.get("id") == self.tooltip_for:
                    day["count"] = count
                    break
            self.tooltip_for = None
            self.tooltip_text = []

    def handle_data(self, data: str) -> None:
        if self.tooltip_for:
            self.tooltip_text.append(data)


def fetch_data() -> dict[str, object]:
    request = Request(CONTRIBUTIONS_URL, headers={"User-Agent": "Ihthos-profile-readme/1.0"})
    with urlopen(request, timeout=30) as response:
        source = response.read().decode("utf-8")
    parser = CalendarParser()
    parser.feed(source)
    days = sorted((day for day in parser.days if day.get("date")), key=lambda item: str(item["date"]))
    if not days:
        raise RuntimeError("GitHub returned no contribution days; refusing to overwrite data")

    total_match = re.search(r"([\d,]+)\s+contributions?\s+in the last year", source)
    total = int(total_match.group(1).replace(",", "")) if total_match else sum(int(day["count"]) for day in days)
    monthly: defaultdict[str, int] = defaultdict(int)
    for day in days:
        monthly[str(day["date"])[:7]] += int(day["count"])

    active_dates = {date.fromisoformat(str(day["date"])) for day in days if int(day["count"]) > 0}
    current = 0
    cursor = date.fromisoformat(str(days[-1]["date"]))
    while cursor in active_dates:
        current += 1
        cursor = date.fromordinal(cursor.toordinal() - 1)
    longest = run = 0
    for day in days:
        run = run + 1 if int(day["count"]) > 0 else 0
        longest = max(longest, run)

    return {"username": USERNAME, "source": CONTRIBUTIONS_URL, "fetched_at": date.today().isoformat(), "total": total, "current_streak": current, "longest_streak": longest, "monthly": dict(sorted(monthly.items())), "days": [{"date": day["date"], "count": day["count"], "level": day["level"]} for day in days], "profile": fetch_profile_stats()}


def fetch_profile_stats() -> dict[str, int]:
    """Fetch the public profile counts used by the dashboard card."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def get_json(path: str) -> object:
        url = path if path.startswith("http") else f"{API_URL}{path}"
        request = Request(url, headers={**headers, "User-Agent": "Ihthos-profile-readme/1.0"})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    profile = get_json(f"/users/{USERNAME}")
    repositories = get_json(f"/users/{USERNAME}/repos?per_page=100&type=owner&sort=updated")
    if not isinstance(profile, dict) or not isinstance(repositories, list):
        raise RuntimeError("GitHub API returned an unexpected profile response")

    language_totals: defaultdict[str, int] = defaultdict(int)
    for repo in repositories:
        if not isinstance(repo, dict) or not isinstance(repo.get("languages_url"), str):
            continue
        language_data = get_json(str(repo["languages_url"]))
        if isinstance(language_data, dict):
            for language, size in language_data.items():
                language_totals[str(language)] += int(size)

    total_bytes = sum(language_totals.values())
    languages = [
        {"name": language, "size": size, "percentage": round(size * 100 / total_bytes), "color": LANGUAGE_COLORS.get(language, "#8b949e")}
        for language, size in sorted(language_totals.items(), key=lambda item: item[1], reverse=True)
    ] if total_bytes else []
    created_at = str(profile.get("created_at", ""))
    created_year = int(created_at[:4]) if created_at[:4].isdigit() else date.today().year

    return {
        "public_repos": int(profile.get("public_repos", 0)),
        "stars": sum(int(repo.get("stargazers_count", 0)) for repo in repositories if isinstance(repo, dict)),
        "followers": int(profile.get("followers", 0)),
        "years_active": max(1, date.today().year - created_year + 1),
        "languages": languages,
    }


def write_stats_card(payload: dict[str, object]) -> None:
    stats = payload.get("profile")
    if not isinstance(stats, dict):
        raise RuntimeError("Missing profile statistics; refusing to render an incomplete card")
    items = [("Total Repos", "public_repos"), ("Total Stars", "stars"), ("Followers", "followers"), ("Years Active", "years_active")]
    cards = []
    for index, (label, key) in enumerate(items):
        x = 22 + index * 197
        value = escape(f"{int(stats[key]):,}")
        cards.append(f'''<g transform="translate({x} 54)"><rect class="stat" width="178" height="92" rx="12"/><text x="18" y="35" class="number">{value}</text><text x="18" y="63" class="label">{escape(label)}</text></g>''')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="820" height="170" viewBox="0 0 820 170" role="img" aria-labelledby="title desc">
  <title id="title">GitHub statistics for {USERNAME}</title><desc id="desc">Public repository, star, follower, and following counts.</desc>
  <style>
    .frame {{ fill:#0d1117; stroke:#30363d; stroke-width:2; }} .eyebrow {{ fill:#8b949e; font:600 12px ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:1px; }}
    .heading {{ fill:#f0f6fc; font:700 18px ui-monospace,SFMono-Regular,Menlo,monospace; }} .stat {{ fill:#161b22; stroke:#30363d; }}
    .number {{ fill:#f0f6fc; font:700 25px ui-monospace,SFMono-Regular,Menlo,monospace; }} .label {{ fill:#8b949e; font:13px ui-monospace,SFMono-Regular,Menlo,monospace; }}
  </style>
  <rect class="frame" x="1" y="1" width="818" height="168" rx="14"/><text x="22" y="27" class="eyebrow">PROFILE SNAPSHOT</text><text x="22" y="47" class="heading">A snapshot of the public work</text>{''.join(cards)}
</svg>
'''
    (ROOT / "profile-stats.svg").write_text(svg, encoding="utf-8")


def write_language_card(payload: dict[str, object]) -> None:
    stats = payload.get("profile")
    languages = stats.get("languages") if isinstance(stats, dict) else None
    if not isinstance(languages, list):
        raise RuntimeError("Missing language statistics; refusing to render an incomplete card")
    languages = [language for language in languages if isinstance(language, dict)][:5]
    total = sum(int(language.get("size", 0)) for language in languages)
    if total <= 0:
        raise RuntimeError("GitHub returned no language bytes; refusing to render an empty card")

    size, stroke, radius = 118, 18, 45
    circumference = 2 * 3.141592653589793 * radius
    segments, legend = [], []
    offset = 0.0
    for index, language in enumerate(languages):
        percentage = int(language.get("percentage", 0))
        exact_percentage = int(language.get("size", 0)) * 100 / total
        color = escape(str(language.get("color", "#8b949e")))
        dash = exact_percentage / 100 * circumference
        segments.append(f'<circle cx="72" cy="90" r="{radius}" fill="none" stroke="{color}" stroke-width="{stroke}" stroke-dasharray="{dash:.2f} {circumference:.2f}" stroke-dashoffset="{-offset / 100 * circumference:.2f}"/>')
        y = 43 + index * 25
        legend.append(f'<circle cx="180" cy="{y - 4}" r="4" fill="{color}"/><text x="193" y="{y}" class="lang">{escape(str(language.get("name", "Unknown")))}</text><text x="380" y="{y}" text-anchor="end" class="percent">{percentage}%</text>')
        offset += exact_percentage

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="430" height="170" viewBox="0 0 430 170" role="img" aria-labelledby="title desc">
  <title id="title">Languages used across public repositories</title><desc id="desc">Top programming languages by bytes in public repositories.</desc>
  <style>
    .frame {{ fill:#0d1117; stroke:#30363d; stroke-width:2; }} .label {{ fill:#8b949e; font:600 11px ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:1px; }}
    .lang {{ fill:#f0f6fc; font:13px ui-monospace,SFMono-Regular,Menlo,monospace; }} .percent {{ fill:#8b949e; font:13px ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .ring {{ transform:rotate(-90deg); transform-origin:72px 90px; }}
  </style>
  <rect class="frame" x="1" y="1" width="428" height="178" rx="12"/>
  <g class="ring">{''.join(segments)}</g><text x="72" y="94" text-anchor="middle" class="label">TOP</text><text x="72" y="109" text-anchor="middle" class="label">LANGS</text>{''.join(legend)}
</svg>
'''
    (ROOT / "language-card.svg").write_text(svg.replace('height="170" viewBox="0 0 430 170"', 'height="180" viewBox="0 0 430 180"'), encoding="utf-8")


def write_tech_stack_card() -> None:
    pills = [
        ("Python", "#a371f7", "#ffffff", 82), ("FastAPI", "#009688", "#ffffff", 88), ("C++", "#f34b7d", "#ffffff", 64), ("CUDA", "#3A4E3A", "#ffffff", 70),
        ("Vulkan", "#8f7ee6", "#0d1117", 74), ("React", "#61dafb", "#0d1117", 70), ("TypeScript", "#3178c6", "#ffffff", 96),
        ("Cloudflare Workers", "#f38020", "#0d1117", 164),
    ]
    pills_markup = []
    positions = [(22, 43), (114, 43), (212, 43), (290, 43), (22, 78), (106, 78), (192, 78), (22, 113)]
    for (name, color, text_color, width), (x, y) in zip(pills, positions):
        pills_markup.append(f'<g><rect x="{x}" y="{y}" width="{width}" height="24" rx="6" fill="{color}" stroke="{color}"/><text x="{x + width / 2}" y="{y + 16}" text-anchor="middle" fill="{text_color}" class="tech">{escape(name)}</text></g>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="430" height="168" viewBox="0 0 430 168" role="img" aria-labelledby="title desc">
  <title id="title">Core technologies</title><desc id="desc">Color-coded technologies used in Kazi's public projects.</desc>
  <style>
    .frame {{ fill:#0d1117; stroke:#30363d; stroke-width:2; }} .heading {{ fill:#f0f6fc; font:700 15px ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .tech {{ font:600 12px ui-monospace,SFMono-Regular,Menlo,monospace; }}
  </style>
  <rect class="frame" x="1" y="1" width="428" height="166" rx="12"/><text x="22" y="27" class="heading">Core Technologies</text>{''.join(pills_markup)}
</svg>
'''
    (ROOT / "tech-stack-filled.svg").write_text(svg, encoding="utf-8")


def write_heatmap(payload: dict[str, object]) -> None:
    days = payload["days"]
    assert isinstance(days, list)
    first = date.fromisoformat(str(days[0]["date"]))
    first_sunday = date.fromordinal(first.toordinal() - (first.weekday() + 1) % 7)
    cell, gap, left, top = 12, 4, 26, 34
    cells = []
    max_column = 0
    for day in days:
        assert isinstance(day, dict)
        parsed = date.fromisoformat(str(day["date"]))
        sunday = date.fromordinal(parsed.toordinal() - (parsed.weekday() + 1) % 7)
        column = (sunday.toordinal() - first_sunday.toordinal()) // 7
        max_column = max(max_column, column)
        row = (parsed.weekday() + 1) % 7
        level = max(0, min(5, int(day.get("level", 0))))
        index = column * 7 + row
        x, y = left + column * (cell + gap), top + row * (cell + gap)
        cells.append(f'<rect class="cell" style="--i:{index}" x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" fill="{PALETTE[level]}"><title>{day["date"]}: {day.get("count", 0)} contributions</title></rect>')

    width, height = left + (max_column + 1) * (cell + gap) + 16, 154
    total = f'{int(payload["total"]):,}'
    legend = ''.join(f'<rect x="{100 + i * 17}" y="135" width="12" height="12" rx="3" fill="{color}"/>' for i, color in enumerate(PALETTE))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{total} contributions in the last year</title><desc id="desc">A contribution calendar for GitHub user {USERNAME}.</desc>
  <style>
    .frame {{ fill:#0d1117; stroke:#30363d; stroke-width:2; }} .heading {{ fill:#f0f6fc; font:700 15px ui-monospace,SFMono-Regular,Menlo,monospace; }} .meta {{ fill:#8b949e; font:12px ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .cell {{ opacity:0; transform-box:fill-box; transform-origin:center; animation:reveal .5s ease-out calc(var(--i) * 7ms) forwards; }} @keyframes reveal {{ from {{ opacity:0; transform:translateY(-5px) scale(.75); }} to {{ opacity:1; transform:translateY(0) scale(1); }} }}
  </style>
  <rect class="frame" x="1" y="1" width="{width - 2}" height="{height - 2}" rx="12"/><text x="26" y="21" class="heading">{total} contributions in the last year</text>{''.join(cells)}
  <text x="26" y="144" class="meta">less</text>{legend}<text x="210" y="144" class="meta">more</text>
</svg>
'''
    (ROOT / "contrib-heatmap.svg").write_text(svg, encoding="utf-8")


def main() -> int:
    payload = fetch_data()
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_stats_card(payload)
    write_language_card(payload)
    write_tech_stack_card()
    write_heatmap(payload)
    print(f"wrote {len(payload['days'])} days and {int(payload['total']):,} contributions")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise
