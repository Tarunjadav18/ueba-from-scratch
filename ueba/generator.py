"""Synthetic organization with varied benign routines and planted attack stories."""
from __future__ import annotations

import numpy as np
import pandas as pd

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
    "NL": (52.3676, 4.9041, "Amsterdam"),
    "NG": (6.5244, 3.3792, "Lagos"),
    "DE": (50.1109, 8.6821, "Frankfurt"),
    "SG": (1.3521, 103.8198, "Singapore"),
}


def _attack_schedule(rng: np.random.Generator, departments: list[str], days: int) -> dict[tuple[int, int], str]:
    """Plant the same mix of stories on seed-specific victims and dates."""
    stories = [
        ("brute_force_takeover", 1), ("impossible_travel", 1),
        ("off_hours_exfiltration", 1), ("api_key_exfiltration", 1),
        ("slow_insider", 5), ("privilege_escalation", 1), ("lateral_movement", 1),
        ("cryptomining", 3), ("password_spray", 1), ("travel_exfiltration", 1),
        ("admin_account_abuse", 1),
    ]
    if not departments or days <= 0:
        return {}

    remaining = set(range(len(departments)))
    schedule: dict[tuple[int, int], str] = {}
    for scenario, duration in stories:
        if not remaining:
            break
        if duration > days:
            continue
        preferred_department = {"privilege_escalation": "Sales", "admin_account_abuse": "IT-Admin"}.get(scenario)
        preferred = [i for i in remaining if departments[i] == preferred_department]
        candidates = preferred or list(remaining)
        victim = int(rng.choice(candidates))
        remaining.remove(victim)
        latest_start = days - duration
        # Keep incidents in the later part of the timeline so earlier behavior
        # remains available for learning, while allowing each seed to move them.
        earliest_start = min(latest_start, int(round(days * 0.58)))
        first_day = int(rng.integers(earliest_start, latest_start + 1))
        for day in range(first_day, first_day + duration):
            schedule[(int(victim), day)] = scenario
    return schedule


def _benign_anomaly_schedule(rng: np.random.Generator, departments: list[str], days: int,
                             attack_schedule: dict[tuple[int, int], str]) -> dict[str, list[int]]:
    """Choose four unlabeled but unusual behaviors for the synthetic organization."""
    result: dict[str, list[int]] = {}
    if days <= 0:
        return result
    monitoring_start = min(days - 1, int(round(days * 0.5)))
    latest_trip_start = max(monitoring_start, days - 3)
    attacked_users = {user_no for user_no, _ in attack_schedule}
    for department in ("Engineering", "Sales", "IT-Admin", "HR"):
        candidates = [i for i, value in enumerate(departments)
                      if value == department and i not in attacked_users]
        if candidates:
            user_no = int(rng.choice(candidates))
            max_start = latest_trip_start if department == "Sales" else days - 1
            first_day = int(rng.integers(monitoring_start, max_start + 1))
            result[department] = [user_no, first_day]
    return result


def make_demo(seed: int = 42, users: int = 48, days: int = 60) -> pd.DataFrame:
    """Make 48 users/60 devices over 60 days with detailed synthetic telemetry.

    The labels exist only for later evaluation. They are not used to build
    profiles, fit the unsupervised ensemble, or choose alert thresholds.
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-01-01", tz="UTC")
    rows: list[dict] = []
    people = list(USERS) + [f"user{n + 1:02d}" for n in range(len(USERS), users)]
    departments = list(DEPARTMENTS) + ["Engineering"] * max(0, users - len(DEPARTMENTS))
    people = people[:users]
    departments = departments[:users]
    rng.shuffle(people)
    rng.shuffle(departments)
    attack_schedule = _attack_schedule(rng, departments, days)
    benign_anomalies = _benign_anomaly_schedule(rng, departments, days, attack_schedule)

    def add(when: pd.Timestamp, kind: str, user: str, device: str, department: str,
            result: str = "success", *, count: int = 1, label: int = 0, device_label: int | None = None,
            scenario: str = "", **fields) -> None:
        rows.append({"timestamp": when, "event_type": kind, "user": user, "device": device,
                     "department": department, "result": result, "count": count,
                     "label": label, "device_label": label if device_label is None else device_label,
                     "scenario": scenario, **fields})

    for user_no in range(users):
        user = f"{people[user_no]}-s{seed}"
        department = departments[user_no]
        device = f"laptop{user_no + 1:02d}"
        normal_country = str(rng.choice(("IN", "US"), p=(0.2, 0.8)))
        lat, lon, city = LOCATIONS[normal_country]
        normal_domain = str(rng.choice(("intranet.example.com", "docs.google.com",
                                        "mail.example.com", "erp.example.com")))

        for offset in range(days):
            day = start + pd.Timedelta(days=offset)
            attack = attack_schedule.get((user_no, offset))
            label = int(bool(attack))
            device_label = int(bool(attack) and (
                attack not in {"slow_insider", "cryptomining"}
                or attack_schedule.get((user_no, offset - 1)) != attack
            ))
            attack_hour = {
                "brute_force_takeover": 3, "off_hours_exfiltration": 2,
                "password_spray": 3, "admin_account_abuse": 3,
            }.get(attack)
            hour = attack_hour if attack_hour is not None else int(
                np.clip(rng.normal(10.3 if department != "Engineering" else 11.2, 1.4), 7, 19)
            )
            base_time = day + pd.Timedelta(hours=hour)
            if attack == "brute_force_takeover":
                base_time += pd.Timedelta(minutes=10)
            elif attack == "off_hours_exfiltration":
                base_time += pd.Timedelta(minutes=20)
            elif attack == "admin_account_abuse":
                base_time += pd.Timedelta(minutes=5)
            fail_count = int(rng.poisson(0.25))
            file_count = int(max(1, rng.poisson(14 if department == "Finance" else 9)))
            outbound = float(rng.lognormal(2.0, 0.5))
            domain = normal_domain
            country = normal_country
            cpu = float(np.clip(rng.normal(22, 8), 3, 60))
            cpu_duration = 900
            scenario = attack or ""
            if attack == "brute_force_takeover":
                fail_count, country = 45, "US"
            elif attack == "impossible_travel":
                country = "IN"
            elif attack == "off_hours_exfiltration":
                country, file_count, outbound, domain = "US", 60, 700.0, "wetransfer.com"
            elif attack == "api_key_exfiltration":
                file_count, outbound, domain = 90, 3300.0, "mega.nz"
            elif attack == "slow_insider":
                incident_day = sum(
                    1 for previous_day in range(offset)
                    if attack_schedule.get((user_no, previous_day)) == attack
                )
                outbound = (120.0, 415.0, 710.0, 1005.0, 1300.0)[incident_day]
                domain = "dropbox.com"
            elif attack == "cryptomining":
                cpu, cpu_duration = 96.0, 4 * 3600
            elif attack == "password_spray":
                fail_count, country = 30, "US"
            elif attack == "travel_exfiltration":
                country, outbound, domain = "IN", 1200.0, "mega.nz"
            elif attack == "admin_account_abuse":
                country = "DE"

            # Authentication: retain precise timestamps and location for causal rules.
            if attack != "password_spray":
                add(base_time, "auth", user, device, department, count=1, label=label,
                    device_label=device_label, scenario=scenario, result="success",
                    source_ip=("185.220.101.7" if attack == "brute_force_takeover"
                               else f"10.20.{user_no % 250}.{int(rng.integers(2, 245))}"),
                    country=country, city=LOCATIONS[country][2], lat=LOCATIONS[country][0], lon=LOCATIONS[country][1])
            if attack == "impossible_travel":
                location = "NL"
                add(base_time + pd.Timedelta(minutes=70), "auth", user, device, department, count=1, label=1,
                    device_label=device_label, scenario=scenario, result="success", source_ip="185.44.10.8",
                    country=location, city=LOCATIONS[location][2], lat=LOCATIONS[location][0], lon=LOCATIONS[location][1])
            if attack == "travel_exfiltration":
                location = "NG"
                add(base_time + pd.Timedelta(minutes=70), "auth", user, device, department, count=1, label=1,
                    device_label=device_label, scenario=scenario, result="success", source_ip="196.12.44.8",
                    country=location, city=LOCATIONS[location][2], lat=LOCATIONS[location][0], lon=LOCATIONS[location][1])
            if fail_count:
                add(base_time - pd.Timedelta(minutes=5), "auth", user, device, department, result="failure",
                    count=fail_count, label=label, device_label=device_label, scenario=scenario,
                    source_ip=("185.220.101.7" if attack in {"brute_force_takeover", "password_spray"}
                               else f"10.20.{user_no % 250}.9"),
                    country=country, city=LOCATIONS[country][2], lat=LOCATIONS[country][0], lon=LOCATIONS[country][1])

            # Emit individual file operations instead of one pre-aggregated row.
            for serial in range(15):
                add(base_time + pd.Timedelta(minutes=12, seconds=serial), "access", user, device, department,
                    count=1, label=label, device_label=device_label, scenario=scenario, result="success",
                    host=f"fileserver-{department.lower()}.corp",
                    file_name=f"/shares/{department.lower()}/document-{serial % 12}.csv",
                    is_sensitive=False, bytes_out=256 * 1024)
            if attack in {"off_hours_exfiltration", "api_key_exfiltration"}:
                file_total = 60 if attack == "off_hours_exfiltration" else 90
                file_host = "payroll.corp" if attack == "off_hours_exfiltration" else "production-vault.corp"
                for serial in range(file_total):
                    add(base_time + pd.Timedelta(minutes=14, seconds=serial), "access", user, device, department,
                        count=1, label=1, device_label=device_label, scenario=scenario, host=file_host,
                        file_name=(f"/shares/payroll/confidential-{serial:02d}.csv" if attack == "off_hours_exfiltration"
                                   else f"/production/keys/api-key-{serial:02d}.txt"),
                        is_sensitive=True, bytes_out=2 * 1024**2 if attack == "off_hours_exfiltration" else 3 * 1024**2)
            if attack == "lateral_movement":
                for serial in range(12):
                    add(base_time + pd.Timedelta(minutes=15, seconds=serial * 3), "access", user, device, department,
                        count=1, label=1, device_label=device_label, scenario=scenario,
                        host=f"new-host-{serial + 1:02d}.corp", command="ssh / rdp remote session")

            # Emit connection records; the pipeline later summarizes them into one user-day.
            network_domain = "miningpool.example" if attack == "cryptomining" else domain
            network_port = 3333 if attack == "cryptomining" else 443
            for serial in range(15):
                add(base_time + pd.Timedelta(minutes=25, seconds=serial), "network", user, device, department,
                    count=1, label=label, device_label=device_label, scenario=scenario,
                    domain=network_domain, port=network_port,
                    bytes_out=(outbound / 15) * 1024**2,
                    bytes_in=float(rng.uniform(0.1, 30) / 15) * 1024**2, result="success")
            web_category = "business" if "example" in network_domain else "cloud_storage"
            web_domain = network_domain
            if attack == "slow_insider":
                web_category, web_domain = "career", "indeed.com"
            for serial in range(10):
                add(base_time + pd.Timedelta(minutes=27, seconds=serial), "web", user, device, department,
                    label=label, device_label=device_label, scenario=scenario, domain=web_domain,
                    url=f"https://{web_domain}/page/{serial}", category=web_category,
                    result="allowed", blocked=False, file_name="", bytes_out=0)

            # The report models hourly CPU, memory, and disk metadata for each device.
            for sample_hour in range(24):
                sample_time = day + pd.Timedelta(hours=sample_hour)
                sample_cpu = float(np.clip(rng.normal(22, 8), 3, 60))
                if attack == "cryptomining":
                    sample_cpu = 96.0
                add(sample_time, "resource", user, device, department, label=label, device_label=device_label,
                    scenario=scenario, resource_pct=sample_cpu, memory_pct=float(rng.uniform(20, 75)),
                    disk_pct=float(rng.uniform(25, 70)), duration_seconds=3600)

            # Higher-detail event families are planted only in matching attack cases.
            if attack == "privilege_escalation":
                add(base_time + pd.Timedelta(minutes=45), "admin", user, device, department, label=1,
                    device_label=device_label, scenario=scenario, result="success", is_admin=True,
                    target_user=user, host="domain-controller.corp",
                    command="net group Domain Admins /add")
            if attack == "admin_account_abuse":
                for serial in range(4):
                    add(base_time + pd.Timedelta(minutes=10 + serial), "admin", user, device, department,
                        label=1, device_label=device_label, scenario=scenario, result="success", is_admin=True,
                        target_user=f"created-user-{serial + 1:02d}", host="domain-controller.corp",
                        command="create domain account")
                add(base_time + pd.Timedelta(minutes=20), "admin", user, device, department,
                    label=1, device_label=device_label, scenario=scenario, result="success", is_admin=True,
                    target_user="Security", host="domain-controller.corp", command="clear security log")

    # Four benign anomalies remain unlabelled: late work, business travel, an
    # internal backup transfer, and access to another department's files.
    for department, (user_no, offset) in benign_anomalies.items():
        user = f"{people[user_no]}-s{seed}"
        device = f"laptop{user_no + 1:02d}"
        day = start + pd.Timedelta(days=offset)
        if department == "Engineering":
            add(day + pd.Timedelta(hours=1), "auth", user, device, department, label=0,
                result="success", country="US", city=LOCATIONS["US"][2], lat=LOCATIONS["US"][0], lon=LOCATIONS["US"][1])
            add(day + pd.Timedelta(hours=1, minutes=5), "access", user, device, department,
                label=0, host="engineering-files.corp", file_name="/engineering/release-notes.txt")
        elif department == "Sales":
            for trip_day in range(3):
                when = day + pd.Timedelta(days=trip_day, hours=9)
                add(when, "auth", user, device, department, label=0, result="success", country="SG",
                    city=LOCATIONS["SG"][2], lat=LOCATIONS["SG"][0], lon=LOCATIONS["SG"][1])
        elif department == "IT-Admin":
            add(day + pd.Timedelta(hours=14), "network", user, device, department, label=0,
                domain="backup.internal", host="backup-01.corp", port=445, bytes_out=20 * 1024**3,
                result="success")
        elif department == "HR":
            for serial in range(11):
                add(day + pd.Timedelta(hours=10, seconds=serial), "access", user, device, department,
                    label=0, host="finance-files.corp", file_name=f"/shares/Finance/file-{serial + 1:02d}.csv")

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
