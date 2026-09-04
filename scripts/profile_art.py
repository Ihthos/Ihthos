#!/usr/bin/env python3
"""Build the profile's token-free contribution data and animated SVG assets."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import date
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

USERNAME = "zidni0"
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "contributions.json"
CONTRIBUTIONS_URL = f"https://github.com/users/{USERNAME}/contributions"
PALETTE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353", "#69f0a0"]


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
    request = Request(CONTRIBUTIONS_URL, headers={"User-Agent": "zidni0-profile-readme/1.0"})
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

    return {"username": USERNAME, "source": CONTRIBUTIONS_URL, "fetched_at": date.today().isoformat(), "total": total, "current_streak": current, "longest_streak": longest, "monthly": dict(sorted(monthly.items())), "days": [{"date": day["date"], "count": day["count"], "level": day["level"]} for day in days]}


def write_info_card() -> None:
    rows = [("Focus", "local AI + applied ML"), ("Builds", "education + civic data"), ("Stack", "Python · C++ · React"), ("Now", "shipping useful software")]
    row_markup = []
    for index, (label, value) in enumerate(rows):
        y = 94 + index * 48
        row_markup.append(f'<g class="row" style="--i:{index}"><text x="34" y="{y}" class="label">{escape(label)}</text><text x="154" y="{y}" class="value">{escape(value)}</text></g>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="490" height="280" viewBox="0 0 490 280" role="img" aria-labelledby="title desc">
  <title id="title">Kazi Islam profile information</title><desc id="desc">A terminal-style card describing Kazi's engineering focus and toolkit.</desc>
  <style>
    .panel {{ fill:#0d1117; stroke:#30363d; stroke-width:2; }} .bar {{ fill:#161b22; }} .dot-red {{ fill:#ff7b72; }} .dot-yellow {{ fill:#d29922; }} .dot-green {{ fill:#7ee787; }}
    .prompt {{ fill:#7ee787; font:600 14px ui-monospace,SFMono-Regular,Menlo,monospace; }} .title {{ fill:#f0f6fc; font:700 18px ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .label {{ fill:#79c0ff; font:600 14px ui-monospace,SFMono-Regular,Menlo,monospace; }} .value {{ fill:#c9d1d9; font:14px ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .row {{ opacity:0; transform:translateY(5px); animation:appear .45s ease-out calc(var(--i) * .12s) forwards; }} @keyframes appear {{ to {{ opacity:1; transform:translateY(0); }} }}
  </style>
  <rect class="panel" x="1" y="1" width="488" height="278" rx="12"/><rect class="bar" x="1" y="1" width="488" height="34" rx="12"/>
  <circle class="dot-red" cx="22" cy="18" r="6"/><circle class="dot-yellow" cx="42" cy="18" r="6"/><circle class="dot-green" cx="62" cy="18" r="6"/>
  <text x="92" y="23" class="prompt">kazi@github:~</text><text x="34" y="66" class="title">$ neofetch --profile</text>{''.join(row_markup)}
</svg>
'''
    (ROOT / "info-card.svg").write_text(svg, encoding="utf-8")


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
    write_info_card()
    write_heatmap(payload)
    print(f"wrote {len(payload['days'])} days and {int(payload['total']):,} contributions")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise
