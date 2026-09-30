"""Canonical, versioned identities; legacy observations never imply provenance."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def legacy_config(row):
    return row.get("config_id") or "legacy-" + digest({"model": row.get("model"),
                                                       "provenance": "unknown"})[:16]


def resume_key(task, config_id, plan_id):
    return digest({"task": task, "config_id": config_id, "plan_id": plan_id})
