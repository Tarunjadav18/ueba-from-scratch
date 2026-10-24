"""Synthetic organization with varied benign routines and planted attack stories."""
from __future__ import annotations

import numpy as np
import pandas as pd

ATTACK_PLAN = {
    (0, 35): "brute_force",
    (1, 36): "impossible_travel",
    (2, 37): "bulk_file_access",
    (3, 38): "data_exfiltration",
    (4, 39): "cloud_exfiltration",
    (5, 40): "new_country_login",
    (7, 44): "first_admin_rights",
    (8, 45): "admin_share_access",
    (9, 46): "bulk_printing",
    (10, 47): "suspicious_powershell",
    (11, 48): "cryptomining",
    (11, 49): "cryptomining",
    (11, 50): "cryptomining",
}
SLOW_USB_DAYS = {(6, day): "slow_usb_exfiltration" for day in range(41, 46)}

USERS = [
    "sana.pillai", "omar.khan", "nisha.menon", "rohan.shah", "diya.rao", "arjun.nair",
    "tara.iyer", "kabir.joshi", "meera.singh", "vivaan.patel", "anaya.reddy", "ishan.das",
]
DEPARTMENTS = ["Finance", "Engineering", "Finance", "Sales", "HR", "Engineering", "Finance", "IT-Admin", "Sales", "HR", "Engineering", "IT-Admin"]
DEPARTMENTS += (["Engineering"] * 11 + ["Sales"] * 8 + ["Finance"] * 5
                + ["HR"] * 4 + ["IT-Admin"] * 3 + ["Management"] * 5)
LOCATIONS = {
    "US": (37.7749, -122.4194, "San Francisco"),
    "IN": (12.9716, 77.5946, "Bengaluru"),
    "GB": (51.5072, -0.1276, "London"),
    "RU": (55.7558, 37.6173, "Moscow"),
}


def make_demo(seed: int = 42, users: int = 48, days: int = 60) -> pd.DataFrame:
    """Make 48 users/60 devices over 60 days with detailed synthetic telemetry.

    The labels exist only for later evaluation. They are not used to build
    profiles, fit the unsupervised ensemble, or choose alert thresholds.
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-01-01", tz="UTC")
    rows: list[dict] = []

    def add(when: pd.Timestamp, kind: str, user: str, device: str, department: str,
            result: str = "success", *, count: int = 1, label: int = 0, scenario: str = "", **fields) -> None:
        rows.append({"timestamp": when, "event_type": kind, "user": user, "device": device,
                     "department": department, "result": result, "count": count,
                     "label": label, "scenario": scenario, **fields})

    for user_no in range(users):
        user = USERS[user_no] if user_no < len(USERS) else f"user{user_no + 1:02d}"
        department = DEPARTMENTS[user_no] if user_no < len(DEPARTMENTS) else "Engineering"
        device = f"laptop{user_no + 1:02d}"
        normal_country = "IN" if user_no % 5 == 1 else "US"
        lat, lon, city = LOCATIONS[normal_country]
        normal_domain = ["intranet.example.com", "docs.google.com", "mail.example.com", "erp.example.com"][user_no % 4]

        for offset in range(days):
            day = start + pd.Timedelta(days=offset)
            attack = ATTACK_PLAN.get((user_no, offset)) or SLOW_USB_DAYS.get((user_no, offset))
            label = int(bool(attack))
            hour = int(np.clip(rng.normal(10.3 if department != "Engineering" else 11.2, 1.4), 7, 19))
            base_time = day + pd.Timedelta(hours=hour)
            fail_count = int(rng.poisson(0.25))
            file_count = int(max(1, rng.poisson(14 if department == "Finance" else 9)))
            outbound = float(rng.lognormal(2.0, 0.5))
            domain = normal_domain
            country = normal_country
            cpu = float(np.clip(rng.normal(22, 8), 3, 60))
            cpu_duration = 900
            scenario = attack or ""
            if attack == "brute_force":
                fail_count = 14
            elif attack == "bulk_file_access":
                file_count = 94
            elif attack in {"data_exfiltration", "cloud_exfiltration"}:
                outbound = 1450.0
                domain = "new-transfer.example.net" if attack == "data_exfiltration" else "drive.google.com"
            elif attack == "new_country_login":
                country = "GB"
            elif attack == "cryptomining":
                cpu, cpu_duration = 96.0, 4 * 3600

            # Authentication: retain precise timestamps and location for causal rules.
            add(base_time, "auth", user, device, department, count=1, label=label, scenario=scenario,
                result="success", source_ip=f"10.20.{user_no % 250}.{int(rng.integers(2, 245))}",
                country=country, city=LOCATIONS[country][2], lat=LOCATIONS[country][0], lon=LOCATIONS[country][1])
            if attack == "impossible_travel":
                add(base_time + pd.Timedelta(minutes=3), "auth", user, device, department, count=1, label=1,
                    scenario=scenario, result="success", source_ip="185.44.10.8", country="GB", city="London",
                    lat=LOCATIONS["GB"][0], lon=LOCATIONS["GB"][1])
            if fail_count:
                add(base_time - pd.Timedelta(minutes=5), "auth", user, device, department, result="failure",
                    count=fail_count, label=label, scenario=scenario, source_ip=f"10.20.{user_no % 250}.9",
                    country=normal_country, city=city, lat=lat, lon=lon)

            # Emit individual file operations instead of one pre-aggregated row.
            for serial in range(15):
                add(base_time + pd.Timedelta(minutes=12, seconds=serial), "access", user, device, department,
                    count=1, label=label, scenario=scenario, result="success",
                    host=f"fileserver-{department.lower()}.corp",
                    file_name=f"/shares/{department.lower()}/document-{serial % 12}.csv",
                    is_sensitive=False, bytes_out=256 * 1024)
            if attack == "bulk_file_access":
                add(base_time + pd.Timedelta(minutes=14), "access", user, device, department, count=83,
                    label=1, scenario=scenario, host="fileserver-executive.corp",
                    file_name="/shares/executive/acquisition.xlsx", is_sensitive=True, bytes_out=200 * 1024**2)

            # Emit connection records; the pipeline later summarizes them into one user-day.
            if attack == "data_exfiltration":
                network_domain = "new-transfer.example.net"
            else:
                network_domain = domain
            for serial in range(15):
                add(base_time + pd.Timedelta(minutes=25, seconds=serial), "network", user, device, department,
                    count=1, label=label, scenario=scenario, domain=network_domain, port=443,
                    bytes_out=(outbound / 15) * 1024**2,
                    bytes_in=float(rng.uniform(0.1, 30) / 15) * 1024**2, result="success")
            web_category = "business" if "example" in network_domain else "cloud_storage"
            web_domain = network_domain
            if attack == "suspicious_powershell":
                web_category, web_domain = "hacking", "nmap-downloads.example"
            for serial in range(10):
                add(base_time + pd.Timedelta(minutes=27, seconds=serial), "web", user, device, department,
                    label=label, scenario=scenario, domain=web_domain,
                    url=f"https://{web_domain}/page/{serial}", category=web_category,
                    result="allowed", blocked=False, file_name="", bytes_out=0)

            # The report models hourly CPU, memory, and disk metadata for each device.
            for sample_hour in range(24):
                sample_time = day + pd.Timedelta(hours=sample_hour)
                sample_cpu = float(np.clip(rng.normal(22, 8), 3, 60))
                if attack == "cryptomining":
                    sample_cpu = 96.0
                add(sample_time, "resource", user, device, department, label=label,
                    scenario=scenario, resource_pct=sample_cpu, memory_pct=float(rng.uniform(20, 75)),
                    disk_pct=float(rng.uniform(25, 70)), duration_seconds=3600)

            # Higher-detail event families are planted only in matching attack cases.
            if attack == "slow_usb_exfiltration":
                for serial in range(5):
                    add(base_time + pd.Timedelta(minutes=40 + serial), "usb", user, device, department,
                        label=1, scenario=scenario, usb_device="USB-NEW-044", file_name=f"payroll-{offset}-{serial}.csv",
                        bytes_out=4 * 1024**2)
            if attack == "first_admin_rights":
                add(base_time + pd.Timedelta(minutes=45), "admin", user, device, department, label=1,
                    scenario=scenario, result="success", is_admin=True, target_user=user)
            if attack == "admin_share_access":
                add(base_time + pd.Timedelta(minutes=45), "share", user, device, department, label=1,
                    scenario=scenario, share_name="\\\\server\\ADMIN$", host="server.corp", result="success")
            if attack == "bulk_printing":
                add(base_time + pd.Timedelta(minutes=45), "print", user, device, department, label=1,
                    scenario=scenario, pages=248, count=1, is_sensitive=True, result="success")
            if attack == "suspicious_powershell":
                add(base_time + pd.Timedelta(minutes=45), "powershell", user, device, department, label=1,
                    scenario=scenario, command="powershell.exe -NoProfile -EncodedCommand invoke-expression downloadstring",
                    result="success")

    # Twelve servers plus 48 employee laptops make the report's 60 devices.
    for server_no in range(12):
        server = f"server{server_no + 1:02d}"
        for offset in range(days):
            day = start + pd.Timedelta(days=offset)
            for sample_hour in range(24):
                when = day + pd.Timedelta(hours=sample_hour)
                add(when, "resource", "unknown-user", server, "IT-Admin", result="sample",
                    resource_pct=float(np.clip(rng.normal(17, 5), 2, 50)), memory_pct=float(rng.uniform(20, 65)),
                    disk_pct=float(rng.uniform(20, 60)), duration_seconds=3600)
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
