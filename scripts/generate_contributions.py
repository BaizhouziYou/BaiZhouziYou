#!/usr/bin/env python3
"""Generate GitHub contribution calendar and activity overview SVG cards.

Uses only Python's standard library and GitHub's GraphQL API.
Requires PROFILE_STATS_TOKEN and optionally PROFILE_STATS_USERNAME.
"""

import json
import os
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"
ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "profile-assets"

PALETTES = {
    "light": {
        "bg": "#ffffff", "fg": "#24292f", "muted": "#57606a", "border": "#d0d7de",
        "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    },
    "dark": {
        "bg": "#0d1117", "fg": "#e6edf3", "muted": "#8b949e", "border": "#30363d",
        "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
    },
}
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def get_contributions(username: str, token: str) -> dict:
    query = """query($login:String!) {
      user(login:$login) {
        contributionsCollection {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays { date contributionCount contributionLevel }
            }
          }
        }
      }
    }"""
    payload = json.dumps({"query": query, "variables": {"login": username}}).encode("utf-8")
    request = Request(API, data=payload, method="POST", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "BaiZhouziYou-profile-stats",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urlopen(request, timeout=35) as response:
            body = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"GitHub GraphQL returned HTTP {exc.code}. Check token and rate limit.") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Failed to connect to GitHub GraphQL: {exc}") from exc
    if body.get("errors"):
        messages = "; ".join(str(e.get("message", "unknown error")) for e in body["errors"])
        raise RuntimeError(f"GitHub GraphQL error: {messages}")
    collection = ((body.get("data") or {}).get("user") or {}).get("contributionsCollection")
    calendar = (collection or {}).get("contributionCalendar")
    if not calendar or not calendar.get("weeks"):
        raise RuntimeError("GitHub returned no contribution calendar data.")
    for key in ("totalCommitContributions", "totalIssueContributions",
                "totalPullRequestContributions", "totalPullRequestReviewContributions"):
        if key not in collection or collection[key] is None:
            raise RuntimeError(f"GitHub returned no {key} metric")
    return collection


def svg_for(calendar: dict, theme: str) -> bytes:
    palette = PALETTES[theme]
    weeks = calendar["weeks"]
    if not 45 <= len(weeks) <= 55:
        raise ValueError(f"Unexpected number of calendar weeks: {len(weeks)}")
    width, height = 940, 218
    x0, y0 = 51, 74
    step = min(16.0, 854.0 / len(weeks))
    square = step - 3.3
    total = int(calendar["totalContributions"])
    fg, muted, border, bg = [palette[k] for k in ("fg", "muted", "border", "bg")]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">GitHub Contribution Activity</title>',
        f'<desc id="desc">{total} contributions in the past year, displayed as a calendar heatmap.</desc>',
        f'<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="12" fill="{bg}" stroke="{border}"/>',
        '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif">',
        f'<text x="22" y="30" font-size="16" font-weight="600" fill="{fg}">{total:,} contributions in the last year</text>',
    ]

    # The contributionCalendar comes in Sunday-to-Saturday weeks.
    prev_month = None
    previous_month_x = -100
    for i, week in enumerate(weeks):
        days = week.get("contributionDays", [])
        for day in days:
            day_date = date.fromisoformat(day["date"])
            # Show a month label at the first occurrence of the month, even
            # when its first day falls in the middle of a week.
            if day_date.month != prev_month:
                x = x0 + i * step
                if x - previous_month_x >= 37:
                    lines.append(f'<text x="{x:.1f}" y="59" font-size="11" fill="{muted}">{MONTHS[day_date.month-1]}</text>')
                    previous_month_x = x
                prev_month = day_date.month
            row = (day_date.weekday() + 1) % 7
            level = LEVELS.get(day["contributionLevel"], 0)
            count = int(day["contributionCount"])
            x = x0 + i * step
            y = y0 + row * step
            label = escape(f"{count} contribution{'s' if count != 1 else ''} on {day_date.isoformat()}")
            lines.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{square:.2f}" height="{square:.2f}" rx="2.1" fill="{palette["levels"][level]}"><title>{label}</title></rect>')

    for label, row in [("Mon", 1), ("Wed", 3), ("Fri", 5)]:
        lines.append(f'<text x="20" y="{y0 + row*step + 10:.1f}" font-size="11" fill="{muted}">{label}</text>')

    lines.extend([
        f'<text x="20" y="197" font-size="11" fill="{muted}">Based on public GitHub contribution activity</text>',
        f'<text x="{width-207}" y="197" font-size="11" fill="{muted}">Less</text>',
    ])
    for i, color in enumerate(palette["levels"]):
        lines.append(f'<rect x="{width-174 + i*19}" y="186" width="13" height="13" rx="2" fill="{color}"/>')
    lines.extend([f'<text x="{width-66}" y="197" font-size="11" fill="{muted}">More</text>', '</g>', '</svg>'])
    return ("\n".join(lines) + "\n").encode("utf-8")


def activity_svg(collection: dict, theme: str) -> bytes:
    """Render the GitHub-style four-direction contribution overview with real data.

    Percentages are shares of these four contribution types in the selected
    GitHub contributionsCollection period, not arbitrary personal scores.
    """
    c = PALETTES[theme]
    bg, fg, muted, border = [c[k] for k in ("bg", "fg", "muted", "border")]
    accent = "#238636" if theme == "light" else "#3fb950"
    axis = "#d8dee4" if theme == "light" else "#30363d"
    counts = [int(collection[k]) for k in (
        "totalCommitContributions", "totalPullRequestContributions",
        "totalIssueContributions", "totalPullRequestReviewContributions")]
    if any(n < 0 for n in counts):
        raise ValueError("Contribution counts may not be negative")
    total = sum(counts)
    shares = [(v / total * 100) if total else 0 for v in counts]
    commits, prs, issues, reviews = shares
    cx, cy, radius = 585, 212, 110
    # Directions: up = reviews, right = issues, down = PRs, left = commits.
    points = [(cx, cy - radius * reviews / 100),
              (cx + radius * issues / 100, cy),
              (cx, cy + radius * prs / 100),
              (cx - radius * commits / 100, cy)]
    polygon = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="860" height="404" viewBox="0 0 860 404" role="img" aria-labelledby="activity-title activity-desc">',
        '<title id="activity-title">Activity overview</title>',
        '<desc id="activity-desc">Share of commits, pull requests, issues, and code reviews over the past contribution year</desc>',
        f'<rect x="0.5" y="0.5" width="859" height="403" rx="13" fill="{bg}" stroke="{border}"/>',
        '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif">',
        f'<text x="24" y="38" font-size="22" font-weight="600" fill="{fg}">Activity overview</text>',
        f'<text x="24" y="64" font-size="13" fill="{muted}">Breakdown of contribution types over the past year</text>',
        f'<line x1="310" x2="310" y1="90" y2="365" stroke="{border}"/>',
        f'<text x="24" y="118" font-size="16" font-weight="600" fill="{fg}">Contribution types</text>',
    ]
    labels = ["Commits", "Pull requests", "Issues", "Code reviews"]
    for i, (label, count, share) in enumerate(zip(labels, counts, shares)):
        yy = 155 + i * 52
        lines.append(f'<circle cx="32" cy="{yy-5}" r="5" fill="{accent}"/>')
        lines.append(f'<text x="49" y="{yy}" font-size="16" fill="{fg}">{label}</text>')
        lines.append(f'<text x="282" y="{yy}" font-size="16" font-weight="600" text-anchor="end" fill="{accent}">{count:,}</text>')
        lines.append(f'<text x="49" y="{yy+18}" font-size="12" fill="{muted}">{share:.0f}% of tracked activity</text>')

    # Faint cross with tick marks, then a filled contribution-share silhouette.
    lines.extend([
        f'<line x1="{cx-radius}" y1="{cy}" x2="{cx+radius}" y2="{cy}" stroke="{axis}" stroke-width="2"/>',
        f'<line x1="{cx}" y1="{cy-radius}" x2="{cx}" y2="{cy+radius}" stroke="{axis}" stroke-width="2"/>',
    ])
    for fraction in (0.25, 0.50, 0.75, 1.00):
        t = radius * fraction
        for x, y in [(cx-t,cy), (cx+t,cy), (cx,cy-t), (cx,cy+t)]:
            if x == cx:
                lines.append(f'<line x1="{x-4:.1f}" x2="{x+4:.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{axis}"/>')
            else:
                lines.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y-4:.1f}" y2="{y+4:.1f}" stroke="{axis}"/>')
    lines.append(f'<polygon points="{polygon}" fill="{accent}" fill-opacity="0.14" stroke="{accent}" stroke-opacity="0.7" stroke-width="1.5"/>')
    for x, y in points:
        lines.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{accent}" stroke-width="5" stroke-linecap="round"/>')
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{accent}"/>')
    lines.append(f'<circle cx="{cx}" cy="{cy}" r="4" fill="{accent}"/>')
    # Labels are outside the axis so even a 100% value does not overlap them.
    for x,y,text,anchor in [
        (cx,77,f"{reviews:.0f}% Code reviews","middle"),
        (cx,365,f"{prs:.0f}% Pull requests","middle"),
        (454,cy+5,f"{commits:.0f}% Commits","end"),
        (715,cy+5,f"{issues:.0f}% Issues","start"),
    ]:
        lines.append(f'<text x="{x}" y="{y}" font-size="14" text-anchor="{anchor}" fill="{muted}">{text}</text>')
    lines.append(f'<text x="24" y="381" font-size="12" fill="{muted}">Percentages are based on these four tracked contribution types.</text>')
    lines.extend(['</g>', '</svg>'])
    return ("\n".join(lines) + "\n").encode("utf-8")


def main():
    token = os.environ.get("PROFILE_STATS_TOKEN", "").strip()
    username = os.environ.get("PROFILE_STATS_USERNAME", "BaizhouziYou").strip()
    if not token:
        raise SystemExit("PROFILE_STATS_TOKEN is missing; set the SUMMARY_GITHUB_TOKEN repository secret.")
    collection = get_contributions(username, token)
    # Render everything in memory before touching output files.
    images = {}
    for theme in PALETTES:
        images[f"contributions-{theme}"] = svg_for(collection["contributionCalendar"], theme)
        images[f"activity-{theme}"] = activity_svg(collection, theme)
    DEST.mkdir(parents=True, exist_ok=True)
    for name, data in images.items():
        path = DEST / f"{name}.svg"
        tmp = path.with_suffix(".svg.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print(f"Generated {path.relative_to(ROOT)} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
