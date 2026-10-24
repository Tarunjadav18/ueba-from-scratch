"""Analyst-friendly event timeline and website visit summaries."""
from __future__ import annotations

import pandas as pd


def website_summary(events: pd.DataFrame, user: str, day: str, previous_domains: set[str] | None = None) -> pd.DataFrame:
    web = events[(events["user"].eq(user)) & events["event_type"].eq("web")].copy()
    if web.empty:
        return pd.DataFrame(columns=["domain", "visits", "minutes", "bytes_in_mb", "bytes_out_mb", "blocked", "new_site", "categories"])
    web["timestamp"] = pd.to_datetime(web["timestamp"], utc=True)
    web = web[web["timestamp"].dt.strftime("%Y-%m-%d").eq(day)].sort_values("timestamp")
    previous_domains = previous_domains or set()
    rows = []
    for domain, group in web.groupby("domain"):
        group = group.sort_values("timestamp")
        gaps = group["timestamp"].diff().dt.total_seconds().fillna(10**9)
        visits = int((gaps > 300).sum())
        # Estimate minutes from request gaps; this is a heuristic, not browser time-on-page.
        minutes = float(sum(min(max(gap, 0), 300) for gap in gaps.iloc[1:]) / 60 + max(1, visits))
        rows.append({
            "domain": domain or "(unknown domain)", "visits": visits, "minutes": round(minutes, 1),
            "bytes_in_mb": round(float(group["bytes_in"].sum() / 1024**2), 2),
            "bytes_out_mb": round(float(group["bytes_out"].sum() / 1024**2), 2),
            "blocked": int(group["blocked"].astype(bool).sum()), "new_site": domain not in previous_domains,
            "categories": ", ".join(sorted({x for x in group["category"].astype(str) if x})),
        })
    return pd.DataFrame(rows).sort_values(["minutes", "bytes_out_mb"], ascending=False).reset_index(drop=True)


def activity_story(events: pd.DataFrame, user: str, day: str, alert_reason: str = "") -> list[dict]:
    """Build one chronological, plain-language account of selected-day activity."""
    data = events[events["user"].eq(user)].copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data = data[data["timestamp"].dt.strftime("%Y-%m-%d").eq(day)].sort_values("timestamp")
    story = []
    previous_text = None
    repeats = 0
    for _, row in data.iterrows():
        kind = row["event_type"]
        if kind == "auth":
            text = f"{row['result']} login from {row['country'] or 'an unlocated address'} ({row['source_ip'] or 'IP unavailable'})."
        elif kind == "web":
            status = "was blocked by the web filter" if bool(row["blocked"]) else "was allowed"
            text = f"Visited {row['domain'] or row['url'] or 'an unclassified site'} ({row['category'] or 'uncategorized'}); request {status}."
        elif kind == "access":
            qualifier = "sensitive " if bool(row["is_sensitive"]) else ""
            text = f"Accessed {int(row['count'])} {qualifier}file/action record(s) on {row['host'] or 'a host'}: {row['file_name'] or 'path not recorded'}."
        elif kind == "usb":
            text = f"Used removable device {row['usb_device'] or 'with unknown identity'}; file {row['file_name'] or 'not recorded'}."
        elif kind == "admin":
            as_user = f" as {row['target_user']}" if row["target_user"] else ""
            text = f"Used administrative privileges{as_user}."
        elif kind == "share":
            text = f"Accessed shared folder {row['share_name'] or 'not recorded'}."
        elif kind == "print":
            text = f"Printed {int(row['pages'])} page(s){' from a sensitive job' if bool(row['is_sensitive']) else ''}."
        elif kind == "powershell":
            text = f"Ran PowerShell command: {row['command'] or 'command text unavailable'}."
        elif kind == "network":
            text = f"Transferred {row['bytes_out'] / 1024**2:.1f} MB out and {row['bytes_in'] / 1024**2:.1f} MB in with {row['domain'] or 'an unknown destination'}."
        elif kind == "resource":
            text = f"Device resource sample: CPU {row['resource_pct']:.0f}%, memory {row['memory_pct']:.0f}%, disk {row['disk_pct']:.0f}%."
        else:
            text = f"Observed {kind} event ({row['result']})."
        if text == previous_text and kind in {"auth", "web", "network", "resource"}:
            repeats += 1
            continue
        if repeats:
            story[-1]["text"] += f" (and {repeats} similar repeated event(s))"
            repeats = 0
        story.append({"time": row["timestamp"].strftime("%H:%M:%S UTC"), "event_type": kind,
                      "text": text, "flagged": bool(alert_reason) and (kind in {"auth", "access", "network", "usb", "admin", "share", "print", "powershell", "web"})})
        previous_text = text
    if repeats:
        story[-1]["text"] += f" (and {repeats} similar repeated event(s))"
    return story
