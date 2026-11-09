import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from diffwatch import diff


SAMPLE_OLD = {
    "port": {"tcp:22": "0.0.0.0:22", "tcp:8095": "0.0.0.0:8095"},
    "unit": {"system:sshd.service": "enabled", "user:trafficlens.service": "enabled"},
    "cron": {"/etc/crontab": "abc123"},
    "package": {"bash-5.1-8": "", "curl-7.76-3": ""},
}


def test_no_changes():
    assert diff(SAMPLE_OLD, json.loads(json.dumps(SAMPLE_OLD))) == []


def test_new_port_is_detected():
    new = json.loads(json.dumps(SAMPLE_OLD))
    new["port"]["tcp:4444"] = "0.0.0.0:4444"
    ev = diff(SAMPLE_OLD, new)
    assert ("port", "added", "tcp:4444", "0.0.0.0:4444") in ev


def test_removed_unit():
    new = json.loads(json.dumps(SAMPLE_OLD))
    del new["unit"]["user:trafficlens.service"]
    ev = diff(SAMPLE_OLD, new)
    assert ("unit", "removed", "user:trafficlens.service", "enabled") in ev


def test_changed_cron():
    new = json.loads(json.dumps(SAMPLE_OLD))
    new["cron"]["/etc/crontab"] = "fff999"
    ev = diff(SAMPLE_OLD, new)
    assert ("cron", "changed", "/etc/crontab", "abc123 -> fff999") in ev


def test_package_added_and_removed():
    new = json.loads(json.dumps(SAMPLE_OLD))
    new["package"]["evil-1.0-1"] = ""
    del new["package"]["curl-7.76-3"]
    ev = diff(SAMPLE_OLD, new)
    kinds = {(k, e, i) for k, e, i, _ in ev}
    assert ("package", "added", "evil-1.0-1") in kinds
    assert ("package", "removed", "curl-7.76-3") in kinds
