from __future__ import annotations
from pathlib import Path
import pandas as pd
import yaml

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "rules" / "quality_rules.yaml"

def load_rules(path: Path = DEFAULT_RULES_PATH) -> dict:
    if not path.exists():
        return {"rules": {"global": {}, "columns": {}}}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _issue(rule, severity, message, count):
    return {"rule": rule, "severity": severity, "message": message, "count": int(count)}

def apply_rules(df: pd.DataFrame, rules: dict | None = None) -> list[dict]:
    cfg = (rules or load_rules()).get("rules", {})
    issues = []
    g = cfg.get("global", {})
    c_rules = cfg.get("columns", {})
    if len(df):
        miss = float(df.isna().sum().sum()) / max(df.size, 1)
        if g.get("max_missing_rate") is not None and miss > float(g["max_missing_rate"]):
            issues.append(_issue("GLOBAL_MISSING_RATE", "HIGH", f"Missing rate {miss:.2%} exceeds {float(g['max_missing_rate']):.2%}.", int(df.isna().sum().sum())))
        dup = float(df.duplicated().sum()) / len(df)
        if g.get("max_duplicate_rate") is not None and dup > float(g["max_duplicate_rate"]):
            issues.append(_issue("GLOBAL_DUPLICATE_RATE", "HIGH", f"Duplicate rate {dup:.2%} exceeds {float(g['max_duplicate_rate']):.2%}.", int(df.duplicated().sum())))
    normalized = {str(c).strip().lower(): c for c in df.columns}
    for requested, rule in c_rules.items():
        col = normalized.get(str(requested).strip().lower())
        if col is None:
            continue
        s = df[col]
        typ = str(rule.get("type", "")).lower()
        if typ == "not_null":
            n = int(s.isna().sum())
            if n: issues.append(_issue("NOT_NULL", "HIGH", f"Column '{col}' has {n} missing values.", n))
        elif typ == "unique":
            n = int(s.duplicated(keep=False).sum())
            if n: issues.append(_issue("UNIQUE", "HIGH", f"Column '{col}' has {n} values in duplicate groups.", n))
        elif typ == "range":
            x = pd.to_numeric(s, errors="coerce")
            mask = pd.Series(False, index=s.index)
            if rule.get("min") is not None: mask |= x < float(rule["min"])
            if rule.get("max") is not None: mask |= x > float(rule["max"])
            n = int(mask.fillna(False).sum())
            if n: issues.append(_issue("RANGE", "HIGH", f"Column '{col}' has {n} values outside configured range.", n))
        elif typ == "regex":
            pattern = str(rule.get("pattern", ""))
            if pattern:
                valid = s.dropna().astype(str).str.fullmatch(pattern)
                n = int((~valid).sum())
                if n: issues.append(_issue("REGEX", "WARNING", f"Column '{col}' has {n} values failing regex validation.", n))
        elif typ == "date":
            parsed = pd.to_datetime(s, errors="coerce")
            n = int((s.notna() & parsed.isna()).sum())
            if n: issues.append(_issue("DATE_VALIDATION", "WARNING", f"Column '{col}' has {n} invalid dates.", n))
    return issues
