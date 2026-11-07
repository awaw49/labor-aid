#!/usr/bin/env python3
"""五城口径文件一致性自检：schema 完整、一裁终局线=最低工资×12、上限=3×社平、来源字段齐。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ["city", "province", "caliber", "verified_at", "params", "arbitration",
            "online", "court", "supervision", "legal_aid", "hotlines"]
PARAMS = ["min_wage_monthly", "min_wage_hourly", "avg_wage_monthly",
          "one_final_award_threshold", "min_wage_source", "avg_wage_source"]

bad = 0
for f in sorted((ROOT / "data" / "city").glob("*.json")):
    d = json.load(open(f, encoding="utf-8"))
    errs = []
    for k in REQUIRED:
        if k not in d:
            errs.append(f"缺字段 {k}")
    p = d.get("params", {})
    for k in PARAMS:
        if k not in p:
            errs.append(f"params 缺 {k}")
    if p.get("one_final_award_threshold") != p.get("min_wage_monthly", 0) * 12:
        errs.append("一裁终局线 ≠ 最低工资×12")
    if p.get("si_base_max"):
        basis = p.get("si_avg_wage_monthly") or p.get("avg_wage_monthly")
        if basis and abs(p["si_base_max"] - basis * 3) > 1:
            errs.append("社保上限 ≠ 3×对应口径社平")
    if not d.get("arbitration"):
        errs.append("无仲裁窗口")
    print(("✗ " if errs else "✓ ") + f.name, ("；".join(errs) if errs else ""))
    bad += bool(errs)
sys.exit(1 if bad else 0)
