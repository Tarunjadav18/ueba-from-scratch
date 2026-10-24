from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Rule:
    identifier: str
    name: str
    severity: float
    technique: str
    predicate: Callable[[pd.Series], bool]


RULES = [
    Rule("R01", "Brute-force success", .80, "T1110 Brute Force", lambda r: r.auth_failures >= 10 and r.auth_success > 0),
    Rule("R02", "Password spray / brute-force attempt", .45, "T1110 Brute Force", lambda r: r.auth_failures >= 10),
    Rule("R03", "Impossible travel", .70, "T1078 Valid Accounts", lambda r: r.impossible_travel > 0),
    Rule("R04", "New login country", .35, "T1078 Valid Accounts", lambda r: r.new_countries > 0),
    Rule("R05", "Repeated rare-hour activity", .35, "T1078 Valid Accounts", lambda r: r.rare_hour_events >= 3),
    Rule("R06", "Unusual bulk file access", .35, "T1005 Data from Local System", lambda r: r.files_or_actions >= 75),
    Rule("R07", "Sensitive files accessed", .45, "T1005 Data from Local System", lambda r: r.sensitive_files >= 5),
    Rule("R08", "Multiple new hosts", .35, "T1021 Remote Services", lambda r: r.new_hosts >= 4),
    Rule("R09", "Large outbound transfer", .45, "T1041 Exfiltration Over C2 Channel", lambda r: r.bytes_out_mb >= 500),
    Rule("R10", "Large cloud-domain upload", .55, "T1567 Exfiltration Over Web Service", lambda r: r.cloud_upload_mb >= 100),
    Rule("R11", "Unusual access denied burst", .35, "T1078 Valid Accounts", lambda r: r.access_denied >= 10),
    Rule("R12", "Proxy block burst", .35, "T1090 Proxy", lambda r: r.blocked_requests >= 8),
    Rule("R13", "Hacking or malware site visit", .45, "T1588.002 Tool", lambda r: r.hacking_site_visits > 0),
    Rule("R14", "Executable from a newly visited site", .55, "T1105 Ingress Tool Transfer", lambda r: r.executable_downloads > 0 and r.new_domains > 0),
    Rule("R15", "Off-hours sensitive printing", .40, "T1074 Data Staged", lambda r: r.off_hours_print_jobs > 0 and r.confidential_print_pages > 0),
    Rule("R16", "Removable media without prior use", .45, "T1052.001 Exfiltration Over USB", lambda r: r.usb_first_use > 0),
    Rule("R17", "First-time removable device", .35, "T1052.001 Exfiltration Over USB", lambda r: r.usb_new_devices > 0),
    Rule("R18", "Sensitive data accessed in bulk", .50, "T1005 Data from Local System", lambda r: r.sensitive_files > 0 and r.sensitive_bytes_mb >= 50),
    Rule("R19", "Repeated off-hours activity", .35, "T1078 Valid Accounts", lambda r: r.off_hours_events >= 5),
    Rule("R20", "Several previously unseen web categories", .35, "T1588 Acquire Capabilities", lambda r: r.new_web_categories >= 2),
    Rule("R21", "Multiple blocked websites", .35, "T1090 Proxy", lambda r: r.blocked_sites >= 5),
    Rule("R22", "Unusually many downloads", .40, "T1105 Ingress Tool Transfer", lambda r: r.downloads >= 5),
    Rule("R23", "Network reconnaissance", .45, "T1046 Network Service Discovery", lambda r: r.distinct_ports >= 10),
    Rule("R24", "First-time administrative privileges", .45, "T1078.002 Domain Accounts", lambda r: r.admin_first_use > 0),
    Rule("R25", "Administrative share access", .55, "T1021.002 SMB/Windows Admin Shares", lambda r: r.admin_share_events > 0),
    Rule("R26", "Four or more new shared folders", .45, "T1135 Network Share Discovery", lambda r: r.new_shared_folders >= 4),
    Rule("R27", "Print volume five times the user's recent median", .40, "T1074 Data Staged", lambda r: r.print_volume_ratio >= 5),
    Rule("R28", "Suspicious PowerShell command", .55, "T1059.001 PowerShell", lambda r: r.suspicious_powershell > 0),
]

DEVICE_RULES = [
    Rule("D01", "High CPU use consistent with resource hijacking", .45, "T1496 Resource Hijacking", lambda r: r.device_cpu_max >= 85 and r.device_cpu_hours_above_85 >= 1),
    Rule("D02", "Large device outbound transfer", .45, "T1041 Exfiltration Over C2 Channel", lambda r: r.device_bytes_out_mb >= 750),
    Rule("D03", "New outbound destination burst", .35, "T1041 Exfiltration Over C2 Channel", lambda r: r.device_new_domains >= 8),
    Rule("D04", "Unusual number of users on one device", .35, "T1078 Valid Accounts", lambda r: r.device_unique_users >= 8),
    Rule("D05", "Port sweep from one device", .45, "T1046 Network Service Discovery", lambda r: r.device_distinct_ports >= 20),
]


def add_rule_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Evaluate the explainable ATT&CK-aligned rule catalogue on each user-day."""
    out = frame.copy()
    out["rule_score"] = 0.0
    out["rule_names"] = ""
    out["rule_ids"] = ""
    out["rule_techniques"] = ""
    for index, row in out.iterrows():
        # Sparse third-party exports may omit fields used by unrelated rules.
        safe_row = row.copy()
        for rule in RULES:
            for name in rule.predicate.__code__.co_names:
                if name not in safe_row.index:
                    safe_row[name] = 0
        fired = [rule for rule in RULES if bool(rule.predicate(safe_row))]
        if not fired:
            continue
        out.at[index, "rule_score"] = max(rule.severity for rule in fired)
        out.at[index, "rule_names"] = "; ".join(rule.name for rule in fired)
        out.at[index, "rule_ids"] = ", ".join(rule.identifier for rule in fired)
        out.at[index, "rule_techniques"] = "; ".join(dict.fromkeys(rule.technique for rule in fired))
    return out


def add_device_rule_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Evaluate the device-specific D01-D05 rule set."""
    out = frame.copy()
    out["rule_score"] = 0.0
    out["rule_names"] = ""
    out["rule_ids"] = ""
    out["rule_techniques"] = ""
    for index, row in out.iterrows():
        safe_row = row.copy()
        for rule in DEVICE_RULES:
            for name in rule.predicate.__code__.co_names:
                if name not in safe_row.index:
                    safe_row[name] = 0
        fired = [rule for rule in DEVICE_RULES if bool(rule.predicate(safe_row))]
        if fired:
            out.at[index, "rule_score"] = max(rule.severity for rule in fired)
            out.at[index, "rule_names"] = "; ".join(rule.name for rule in fired)
            out.at[index, "rule_ids"] = ", ".join(rule.identifier for rule in fired)
            out.at[index, "rule_techniques"] = "; ".join(dict.fromkeys(rule.technique for rule in fired))
    return out
