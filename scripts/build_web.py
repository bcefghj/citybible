#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把判定结果、校准报告、地标数据内联进单文件展示页。

内联而非 fetch 的理由：
1) 评委可能直接双击本地文件打开，file:// 下 fetch 会被 CORS 拦死；
2) 少 3 个请求，在 3 Mbps 出网带宽下首屏更快；
3) 页面自包含，可以随邮件/U盘分发。
"""
from __future__ import annotations

import json, pathlib, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

cases = json.loads((WEB / "demo_cases.json").read_text(encoding="utf-8"))
landmarks = json.loads((WEB / "landmarks.json").read_text(encoding="utf-8"))
calib = json.loads((ROOT / "eval" / "calibration_report.json").read_text(encoding="utf-8"))

runs = [{
    "detector": r["detector"],
    "cm": r["confusion_matrix"],
    "metrics": r["metrics"],
    "latency": r["mean_latency_ms"],
    "dist": r["inlier_distribution"],
} for r in calib["runs"]]

DATA = {
    "cases": cases,
    "landmarks": landmarks,
    "calib": {"generated_at": calib["generated_at"],
              "n": calib["sample_count"], "runs": runs},
    "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
}

tpl = (WEB / "template.html").read_text(encoding="utf-8")
html = tpl.replace("/*__DATA__*/", json.dumps(DATA, ensure_ascii=False))
(WEB / "index.html").write_text(html, encoding="utf-8")
size = (WEB / "index.html").stat().st_size
print("web/index.html 已生成  %.1f KB" % (size / 1024))
