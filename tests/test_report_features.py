from __future__ import annotations

import numpy as np
import pandas as pd

from ueba.cert import load_cert_directory
from ueba.detectors import add_rule_signals
from ueba.evaluate import evaluate
from ueba.experiments import evaluate_experiments
from ueba.features import DEVICE_FEATURES, USER_FEATURES, _haversine_km, daily_features
from ueba.feedback import record, verdict_sets
from ueba.ingest import normalize_events
from ueba.ml import MLEnsemble
from ueba.pipeline import run
from ueba.profiles import robust_profile
from ueba.risk import fuse_risk


def test_normalizer_marks_unlabelled_exports_without_inventing_truth():
    events = normalize_events(pd.DataFrame([{
        "timestamp": "2026-01-01T12:00:00Z", "username": "ACME\\Alice",
        "hostname": "LAPTOP-1", "event_type": "authentication", "status": "allowed",
    }]))
    assert events.loc[0, "user"] == "alice"
    assert events.loc[0, "device"] == "laptop-1"
    assert events.loc[0, "event_type"] == "auth"
    assert events.loc[0, "result"] == "success"
    assert not bool(events.loc[0, "has_ground_truth"])


def test_report_feature_contract_is_44_user_and_19_device_features():
    assert len(USER_FEATURES) == 44
    assert len(DEVICE_FEATURES) == 19


def test_off_hours_excludes_resource_samples_and_travel_uses_speed():
    base = pd.Timestamp("2026-01-01", tz="UTC")
    sf = (37.7749, -122.4194, "US")
    london = (51.5072, -0.1276, "GB")
    rows = []
    for user, second_login_hour in (("slow", 21), ("fast", 10)):
        rows.extend([
            {"timestamp": base + pd.Timedelta(hours=9), "event_type": "auth", "user": user,
             "device": user + "-pc", "result": "success", "lat": sf[0], "lon": sf[1], "country": sf[2]},
            {"timestamp": base + pd.Timedelta(hours=second_login_hour), "event_type": "auth", "user": user,
             "device": user + "-pc", "result": "success", "lat": london[0], "lon": london[1], "country": london[2]},
            {"timestamp": base + pd.Timedelta(hours=1), "event_type": "resource", "user": user,
             "device": user + "-pc", "resource_pct": 20},
            {"timestamp": base + pd.Timedelta(hours=23), "event_type": "resource", "user": user,
             "device": user + "-pc", "resource_pct": 20},
        ])
    user_days, _ = daily_features(normalize_events(pd.DataFrame(rows)))
    slow = user_days.set_index("user").loc["slow"]
    fast = user_days.set_index("user").loc["fast"]
    assert slow["off_hours_events"] == 0
    assert slow["impossible_travel"] == 0  # 12 hours is not faster than a commercial flight.
    assert fast["impossible_travel"] == 1  # A transatlantic trip in one hour is impossible.
    assert _haversine_km(*sf[:2], *london[:2]) > 500


def test_robust_profile_uses_median_and_nonzero_spread():
    history = pd.DataFrame({"uploads": [0, 1, 1, 2, 3, 80], "logins": [1, 1, 1, 1, 2, 2]})
    median, spread = robust_profile(history)
    assert median["uploads"] == 1.5
    assert spread["uploads"] >= 1.0
    assert (spread > 0).all()


def test_rule_alert_includes_plain_name_and_attack_mapping():
    row = {name: 0 for name in USER_FEATURES}
    row.update({"files_or_actions": 0, "usb_first_use": 0, "print_volume_ratio": 0,
                "auth_failures": 12, "auth_success": 1})
    result = add_rule_signals(pd.DataFrame([row])).iloc[0]
    assert result["rule_score"] == 0.80
    assert "Brute-force success" in result["rule_names"]
    assert "T1110" in result["rule_techniques"]


def test_statistics_alone_stays_below_alert_threshold_and_risk_is_bounded():
    frame = pd.DataFrame([
        {"user": "alice", "date": "2026-01-01", "stat_score": 1.0, "peer_score": 0.0,
         "ml_score": 0.0, "rule_score": 0.0, "criticality": 1.3, "analysis_mode": "monitoring"},
        {"user": "bob", "date": "2026-01-01", "stat_score": 1.0, "peer_score": 1.0,
         "ml_score": 1.0, "rule_score": 1.0, "criticality": 1.3, "analysis_mode": "monitoring"},
    ])
    scored = fuse_risk(frame)
    assert scored.loc[0, "daily_risk"] < 45
    assert not bool(scored.loc[0, "alert"])
    assert scored.loc[1, "daily_risk"] == 100
    assert bool(scored.loc[1, "alert"])
    assert scored["daily_risk"].between(0, 100).all()


def test_accumulated_risk_decays_and_emits_one_sustained_alert_on_threshold_crossing():
    spaced = pd.DataFrame([
        {"user": "alice", "date": "2026-01-01", "stat_score": 0.0, "peer_score": 0.0,
         "ml_score": 0.0, "rule_score": 0.20},
        {"user": "alice", "date": "2026-01-04", "stat_score": 0.0, "peer_score": 0.0,
         "ml_score": 0.0, "rule_score": 0.20},
    ])
    decayed = fuse_risk(spaced)
    assert decayed.loc[0, "accumulated_risk"] == 5.0
    assert decayed.loc[1, "accumulated_risk"] == 7.5

    days = pd.date_range("2026-01-01", periods=10, tz="UTC").strftime("%Y-%m-%d")
    gradual = pd.DataFrame({
        "user": "bob", "date": days, "stat_score": 0.0, "peer_score": 0.0,
        "ml_score": 1.0, "rule_score": 0.0, "analysis_mode": "monitoring",
    })
    scored = fuse_risk(gradual)
    assert int(scored["sustained_alert"].sum()) == 1
    assert bool(scored.loc[scored["sustained_alert"], "alert"].iloc[0])


def test_unsupervised_ensemble_returns_bounded_component_scores():
    values = pd.DataFrame(np.random.default_rng(3).normal(size=(18, 4)), columns=list("abcd"))
    model = MLEnsemble(seed=3, trees=20, neighbors=4, autoencoder_layers=(8, 3, 8), autoencoder_max_iter=40)
    model.fit(values)
    scores = model.score(values.iloc[:3])
    assert {"ml_iforest", "ml_lof", "ml_autoencoder", "ml_score"}.issubset(scores.columns)
    assert scores.to_numpy().min() >= 0
    assert scores.to_numpy().max() <= 1


def test_cert_adapter_reads_metadata_only_and_supports_ground_truth_intervals(tmp_path):
    (tmp_path / "LDAP").mkdir()
    (tmp_path / "LDAP" / "2009-11.csv").write_text(
        "user_id,department,content\nalice,Finance,private-field-must-not-load\n", encoding="utf-8")
    (tmp_path / "logon.csv").write_text(
        "id,date,user,pc,activity\n1,2010-01-01 08:00:00,alice,PC-1,Logon\n", encoding="utf-8")
    (tmp_path / "device.csv").write_text(
        "id,date,user,pc,activity\n2,2010-01-01 09:00:00,alice,PC-1,Connect\n", encoding="utf-8")
    (tmp_path / "file.csv").write_text(
        "id,date,user,pc,filename,content\n3,2010-01-01 10:00:00,alice,PC-1,payroll.csv,File Copy\n",
        encoding="utf-8")
    (tmp_path / "http.csv").write_text(
        "id,date,user,pc,url,content\n4,2010-01-01 11:00:00,alice,PC-1,https://jobs.example/search?q=private,private-body\n",
        encoding="utf-8")
    (tmp_path / "email.csv").write_text(
        "id,date,user,pc,to,from,size,attachments,content\n5,2010-01-01 12:00:00,alice,PC-1,x@y,z@x,2000,1,private-body\n",
        encoding="utf-8")
    labels = tmp_path / "labels.csv"
    labels.write_text("user,start,end,scenario\nalice,2010-01-01 08:30,2010-01-01 11:30,exfil\n", encoding="utf-8")

    events = load_cert_directory(tmp_path, label_intervals=labels)
    assert set(events["event_type"]) == {"auth", "usb", "access", "web", "network"}
    assert events["department"].eq("Finance").all()
    assert events["url"].fillna("").str.contains("private").sum() == 0
    assert "private-body" not in events.to_string()
    assert events["has_ground_truth"].all()
    assert events.loc[events["label"].eq(1), "scenario"].eq("exfil").all()


def test_feedback_verdicts_persist_for_next_analysis(tmp_path):
    db = tmp_path / "console.db"
    record(db, "demo", "alice", "2026-01-01", "benign", note="approved travel", username="analyst")
    record(db, "demo", "bob", "2026-01-02", "threat", note="confirmed", username="analyst")
    benign, threat = verdict_sets(db, "demo")
    assert benign == {("alice", "2026-01-01")}
    assert threat == {("bob", "2026-01-02")}


def test_pipeline_scores_without_using_labels_and_evaluation_requires_them():
    rows = []
    for day in range(7):
        rows.append({"timestamp": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=day, hours=10),
                     "event_type": "auth", "user": "alice", "device": "pc-1", "department": "Sales",
                     "result": "success", "country": "US", "lat": 40.0, "lon": -70.0,
                     "label": int(day == 6)})
    events = pd.DataFrame(rows)
    _, scores, devices = run(events, learning_days=5)
    relabelled = events.copy()
    relabelled["label"] = 0
    _, scores_without_attacks, _ = run(relabelled, learning_days=5)
    pd.testing.assert_series_equal(scores["daily_risk"], scores_without_attacks["daily_risk"])
    experiments = evaluate_experiments(scores, thresholds=(45, 70))
    assert experiments["status"] == "ok"
    assert set(experiments["threshold_sweep"]) == {"45", "70"}
    assert set(experiments["component_ablations"]) == {
        "full_model", "without_personal_statistics", "without_peer_profile",
        "without_ml_ensemble", "without_rules", "rules_only",
    }
    assert not devices.empty
    unlabelled_events = events.drop(columns="label")
    _, unlabeled_scores, _ = run(unlabelled_events, learning_days=5)
    assert "No ground-truth labels supplied" in evaluate(unlabeled_scores)["status"]
