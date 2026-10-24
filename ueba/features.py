from __future__ import annotations

import math

import numpy as np
import pandas as pd
from .config import CONFIG

# 44 core user-day features. The optional seven web features are appended only
# when web/proxy detail exists, so flow-only datasets keep the same core model.
USER_FEATURES = [
    "auth_success", "auth_failures", "fail_then_success", "auth_unique_ips",
    "new_countries", "off_hours_events", "rare_hour_events", "impossible_travel",
    "unique_hosts", "new_hosts", "access_files", "sensitive_files", "access_commands",
    "new_file_paths", "access_denied", "usb_events", "usb_new_devices", "usb_files_copied",
    "usb_bytes_mb", "admin_events", "admin_first_use", "admin_as_other",
    "shared_folder_events", "new_shared_folders", "admin_share_events", "print_jobs",
    "print_pages", "confidential_print_pages", "off_hours_print_jobs", "powershell_events",
    "suspicious_powershell", "network_connections", "new_domains", "new_subdomains",
    "bytes_out_mb", "bytes_in_mb", "cloud_upload_mb", "resource_avg_cpu",
    "cpu_hours_above_85", "resource_avg_memory", "resource_avg_disk", "distinct_ports",
    "auth_unique_countries", "sensitive_bytes_mb",
]
WEB_FEATURES = [
    "web_requests", "blocked_requests", "blocked_sites", "hacking_site_visits",
    "new_web_categories", "downloads", "executable_downloads",
]
DEVICE_FEATURES = [
    "device_events", "device_auth_success", "device_auth_failures", "device_unique_users",
    "device_unique_hosts", "device_cpu_avg", "device_cpu_max", "device_cpu_hours_above_85",
    "device_memory_avg", "device_memory_max", "device_disk_avg", "device_disk_max",
    "device_network_connections", "device_bytes_out_mb", "device_bytes_in_mb",
    "device_new_domains", "device_distinct_ports", "device_off_hours_events", "device_usb_events",
]

_CLOUD_DOMAINS = ("drive.google.com", "dropbox.com", "onedrive.live.com", "box.com", "mega.nz", "icloud.com")
_EXECUTABLE_ENDINGS = (".exe", ".dll", ".msi", ".scr", ".ps1", ".bat", ".sh", ".jar", ".dmg")
_SUSPICIOUS_COMMANDS = ("encodedcommand", "downloadstring", "mimikatz", "invoke-expression", "frombase64string", "-bypass", " -enc", "iex(")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a1, o1, a2, o2 = np.radians([lat1, lon1, lat2, lon2])
    a = np.sin((a2 - a1) / 2) ** 2 + np.cos(a1) * np.cos(a2) * np.sin((o2 - o1) / 2) ** 2
    return float(6371 * 2 * np.arcsin(np.sqrt(a)))


def _count_type(g: pd.DataFrame, names: tuple[str, ...]) -> int:
    return int(g["event_type"].isin(names).sum())


def _flag(g: pd.DataFrame, field: str, types: tuple[str, ...] = ()) -> pd.Series:
    flag = g[field].astype(bool) if field in g else pd.Series(False, index=g.index)
    if types:
        flag = flag | g["event_type"].isin(types)
    return flag


def _values(series: pd.Series) -> pd.Series:
    """Non-empty string values without pandas' deprecated empty-string replace path."""
    values = series.dropna().astype(str).str.strip()
    return values[values.ne("")]


def _daily_user_features(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    events = events[events["user"].ne("unknown-user")]
    user_days = list(events.groupby(["user", "date", "department"], sort=True, dropna=False))
    prior_events: dict[str, pd.DataFrame] = {}
    prior_hours: dict[str, list[int]] = {}
    prior_auth_locations: dict[str, list[tuple[pd.Timestamp, float, float]]] = {}
    prior_print_pages: dict[str, list[int]] = {}
    for (user, day, department), g in user_days:
        g = g.sort_values("timestamp")
        previous = prior_events.get(user, events.iloc[0:0])
        old_hosts = set(_values(previous["host"]))
        old_countries = set(_values(previous["country"]))
        old_domains = set(_values(previous["domain"]))
        old_categories = set(_values(previous.loc[previous["event_type"].eq("web"), "category"]))
        old_subdomains: set[str] = set()
        for value in old_domains:
            parts = value.split(".")
            old_subdomains.add(value)
            if len(parts) > 2:
                old_subdomains.add(".".join(parts[:-2]))
        auth = g[g["event_type"].eq("auth")]
        access = g[g["event_type"].eq("access")]
        network = g[g["event_type"].isin(["network", "web"])]
        web = g[g["event_type"].eq("web")]
        usb = g[g["event_type"].eq("usb")]
        admin = g[g["event_type"].eq("admin") | g["is_admin"].astype(bool)]
        shares = g[g["event_type"].eq("share")]
        printing = g[g["event_type"].eq("print")]
        ps = g[g["event_type"].eq("powershell")]
        resource = g[g["event_type"].eq("resource")]
        success = auth["result"].str.lower().isin(["success", "succeeded", "allowed"])
        failures = auth["result"].str.lower().isin(["failure", "failed", "blocked", "deny"])
        known_hours = prior_hours.get(user, [])
        hours = auth["timestamp"].dt.hour
        rare_hours = int(hours.map(lambda h: known_hours.count(int(h)) <= 2).sum()) if known_hours else 0
        fail_then_success = 0
        history = prior_events.get(user, events.iloc[0:0])
        auth_history = history[history["event_type"].eq("auth") & history["result"].str.lower().isin(["failure", "failed"])]
        fail_times = list(auth_history["timestamp"]) + list(auth.loc[failures, "timestamp"])
        for _, row in auth.loc[success].iterrows():
            if any(pd.Timedelta(0) <= row["timestamp"] - t <= pd.Timedelta(minutes=10) for t in fail_times):
                fail_then_success += 1
        impossible_travel = 0
        locs = prior_auth_locations.setdefault(user, [])
        for _, row in auth.loc[success & auth["lat"].notna() & auth["lon"].notna()].iterrows():
            if pd.notna(row["lat"]) and pd.notna(row["lon"]) and (float(row["lat"]) != 0 or float(row["lon"]) != 0):
                if locs:
                    prev_t, prev_lat, prev_lon = locs[-1]
                    hours_between = max((row["timestamp"] - prev_t).total_seconds() / 3600, 1 / 60)
                    distance_km = _haversine_km(prev_lat, prev_lon, float(row["lat"]), float(row["lon"]))
                    if distance_km > 500 and distance_km / hours_between > CONFIG.max_impossible_travel_kmh:
                        impossible_travel += 1
                locs.append((row["timestamp"], float(row["lat"]), float(row["lon"])))
        hour_counts = auth["timestamp"].dt.hour.value_counts().to_dict()
        current_host_values = _values(g["host"])
        current_domain_values = _values(network["domain"])
        new_domains = set(current_domain_values) - old_domains
        new_countries = set(_values(auth["country"])) - old_countries
        current_subs = {".".join(x.split(".")[:-2]) for x in current_domain_values if len(x.split(".")) > 2}
        command_text = ps["command"].fillna("").astype(str).str.lower()
        # Python's sum has an integer zero identity for an empty iterator. A
        # pandas string Series can instead reduce an empty mapped Series to
        # "" on newer pandas releases, which makes int(series.sum()) fail.
        suspicious_powershell = sum(
            any(term in command for term in _SUSPICIOUS_COMMANDS)
            for command in command_text
        )
        urls_files = (web["url"].str.lower() + " " + web["file_name"].str.lower())
        executable = urls_files.map(lambda x: any(x.split("?")[0].endswith(ext) for ext in _EXECUTABLE_ENDINGS)) | web["executable"].astype(bool)
        cloud = network["domain"].str.lower().map(lambda d: any(d == c or d.endswith("." + c) for c in _CLOUD_DOMAINS))
        sensitive = access["is_sensitive"].astype(bool)
        cpu = pd.to_numeric(resource["resource_pct"], errors="coerce").fillna(0)
        duration = pd.to_numeric(resource.get("duration_seconds", pd.Series(900, index=resource.index)), errors="coerce").fillna(900)
        # Resource samples are machine telemetry, not a person working overnight.
        activity = g[g["event_type"].ne("resource")]
        off_hours = activity["timestamp"].dt.hour.map(lambda h: h < 6 or h >= 22)
        blocked = web["blocked"].astype(bool) | web["result"].str.lower().isin(["blocked", "deny", "tcp_denied"])
        print_pages = int(printing["pages"].sum())
        previous_print_pages = prior_print_pages.get(user, [])[-45:]
        print_median = float(np.median(previous_print_pages)) if previous_print_pages else 0.0
        volume_ratio = print_pages / max(print_median, 1.0)
        usb_first_use = int(len(usb) > 0 and not (previous["event_type"] == "usb").any())
        admin_targets = admin.get("target_user", pd.Series("", index=admin.index)).astype(str).str.lower()
        admin_users = admin["user"].astype(str).str.lower()
        admin_as_other = sum(target != user_name for target, user_name in zip(admin_targets, admin_users))
        rows.append({
            "user": user, "date": day, "department": department,
            "scenario": next((str(s) for s in g["scenario"] if str(s)), ""),
            "auth_success": int(auth.loc[success, "count"].sum()), "auth_failures": int(auth.loc[failures, "count"].sum()),
            "fail_then_success": fail_then_success,
            "auth_unique_ips": int(_values(auth["source_ip"]).nunique()),
            "new_countries": len(new_countries), "off_hours_events": int(off_hours.sum()),
            "rare_hour_events": rare_hours, "impossible_travel": impossible_travel,
            "unique_hosts": int(current_host_values.nunique()), "new_hosts": len(set(current_host_values) - old_hosts),
            "access_files": int(_values(access["file_name"]).nunique()),
            "files_or_actions": int(access["count"].sum()),
            "sensitive_files": int(sensitive.sum()), "access_commands": int(_values(access["command"]).count()),
            "new_file_paths": len(set(_values(access["file_name"])) - set(_values(previous["file_name"]))),
            "access_denied": int(access["result"].str.lower().isin(["denied", "blocked", "failure"]).sum()),
            "usb_events": len(usb), "usb_first_use": usb_first_use,
            "usb_new_devices": len(set(_values(usb["usb_device"])) - set(_values(previous["usb_device"]))),
            "usb_files_copied": int(_values(usb["file_name"]).count()),
            "usb_bytes_mb": float(usb["bytes_out"].sum() / 1024**2),
            "admin_events": len(admin), "admin_first_use": int(len(admin) > 0 and len(previous[previous["event_type"].eq("admin")]) == 0),
            "admin_as_other": admin_as_other,
            "shared_folder_events": len(shares), "new_shared_folders": len(set(_values(shares["share_name"])) - set(_values(previous["share_name"]))),
            "admin_share_events": int(shares["share_name"].str.endswith(("C$", "ADMIN$"), na=False).sum()),
            "print_jobs": len(printing), "print_pages": print_pages, "print_volume_ratio": volume_ratio,
            "confidential_print_pages": int(printing.loc[printing["is_sensitive"], "pages"].sum()),
            "off_hours_print_jobs": int((printing["timestamp"].dt.hour.map(lambda h: h < 6 or h >= 22)).sum()),
            "powershell_events": len(ps), "suspicious_powershell": suspicious_powershell,
            "network_connections": len(network), "new_domains": len(new_domains), "new_subdomains": len(current_subs - old_subdomains),
            "bytes_out_mb": float(network["bytes_out"].sum() / 1024**2), "bytes_in_mb": float(network["bytes_in"].sum() / 1024**2),
            "cloud_upload_mb": float(network.loc[cloud, "bytes_out"].sum() / 1024**2),
            "resource_avg_cpu": float(cpu.mean()) if len(cpu) else 0.0,
            "cpu_hours_above_85": float((duration[cpu >= 85].sum() / 3600)) if len(cpu) else 0.0,
            "resource_avg_memory": float(resource["memory_pct"].mean()) if len(resource) else 0.0,
            "resource_avg_disk": float(resource["disk_pct"].mean()) if len(resource) else 0.0,
            "distinct_ports": int(network.loc[network["port"] > 0, "port"].nunique()),
            "auth_unique_countries": int(_values(auth["country"]).nunique()),
            "sensitive_bytes_mb": float(access.loc[sensitive, "bytes_out"].sum() / 1024**2),
            "web_requests": len(web), "blocked_requests": int(blocked.sum()),
            "blocked_sites": int(_values(web.loc[blocked, "domain"]).nunique()),
            "hacking_site_visits": int(web["category"].str.lower().isin(["hacking", "malware", "security_tools", "anonymizer"]).sum()),
            "anonymizer_site_visits": int(web["category"].str.lower().isin(["anonymizer", "proxy", "vpn"]).sum()),
            "new_web_categories": len(set(_values(web["category"])) - old_categories),
            "downloads": int(_values(web["file_name"]).count()),
            "executable_downloads": int(executable.sum()),
            "label": int(g["label"].max()),
            "has_ground_truth": bool(g["has_ground_truth"].any()),
        })
        prior_events[user] = pd.concat([previous, g], ignore_index=True)
        prior_hours.setdefault(user, []).extend(int(h) for h in hours)
        prior_print_pages.setdefault(user, []).append(print_pages)
    return pd.DataFrame(rows)


def _daily_device_features(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    seen_domains: dict[str, set[str]] = {}
    for (device, day), g in events.groupby(["device", "date"], sort=True):
        resource = g[g["event_type"].eq("resource")]
        network = g[g["event_type"].isin(["network", "web"])]
        current_domains = set(_values(network["domain"]))
        new_domains = current_domains - seen_domains.get(str(device), set())
        # Ignore hourly resource sampling when measuring human off-hours activity.
        activity = g[g["event_type"].ne("resource")]
        hours = activity["timestamp"].dt.hour
        rows.append({
            "device": device, "date": day, "device_events": len(g),
            "scenario": next((str(s) for s in g["scenario"] if str(s)), ""),
            "device_auth_success": int(((g["event_type"] == "auth") & g["result"].isin(["success", "succeeded", "allowed"])).sum()),
            "device_auth_failures": int(((g["event_type"] == "auth") & g["result"].isin(["failure", "failed", "blocked", "deny"])).sum()),
            "device_unique_users": int(_values(g["user"]).nunique()),
            "device_unique_hosts": int(_values(g["host"]).nunique()),
            "device_cpu_avg": float(resource["resource_pct"].mean()) if len(resource) else 0.0,
            "device_cpu_max": float(resource["resource_pct"].max()) if len(resource) else 0.0,
            "device_cpu_hours_above_85": float((resource.loc[resource["resource_pct"] >= 85, "duration_seconds"].sum() / 3600)) if len(resource) else 0.0,
            "device_memory_avg": float(resource["memory_pct"].mean()) if len(resource) else 0.0,
            "device_memory_max": float(resource["memory_pct"].max()) if len(resource) else 0.0,
            "device_disk_avg": float(resource["disk_pct"].mean()) if len(resource) else 0.0,
            "device_disk_max": float(resource["disk_pct"].max()) if len(resource) else 0.0,
            "device_network_connections": len(network),
            "device_bytes_out_mb": float(network["bytes_out"].sum() / 1024**2),
            "device_bytes_in_mb": float(network["bytes_in"].sum() / 1024**2),
            "device_new_domains": len(new_domains),
            "device_distinct_ports": int(network.loc[network["port"] > 0, "port"].nunique()),
            "device_off_hours_events": int(((hours < 6) | (hours >= 22)).sum()),
            "device_usb_events": int(g["event_type"].eq("usb").sum()),
            "label": int(g["device_label"].max()),
            "has_ground_truth": bool(g["has_ground_truth"].any()),
        })
        seen_domains.setdefault(str(device), set()).update(current_domains)
    return pd.DataFrame(rows)


def daily_features(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create causal user-day and device-day features from normalized events."""
    e = events.copy()
    e["date"] = e["timestamp"].dt.strftime("%Y-%m-%d")
    if "duration_seconds" not in e:
        e["duration_seconds"] = 900.0
    user = _daily_user_features(e)
    device = _daily_device_features(e)
    return user.sort_values(["user", "date"]).reset_index(drop=True), device.sort_values(["device", "date"]).reset_index(drop=True)
