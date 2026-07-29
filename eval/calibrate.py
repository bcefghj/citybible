#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
城设 CityBible · 裁判校准器

回答的问题不是「系统能不能判」，而是「凭什么信它判得准」。

做法：构造一个每条样本都埋好真值的校准集，让判定引擎在上面跑一遍，
输出查准率 / 查全率 / F1 / 混淆矩阵，以及三类样本的内点数分布。
门禁的可信度由这份报告的召回率兜底，报告随产品一起交付。

校准集三类样本
--------------
POS   同一物理场景的受控视角/光照变换（HPatches 式构造）        真值 = match
NEG-A 完全不同的地点                                          真值 = mismatch
NEG-B AI 用同一提示词重新生成的「同名地点」                     真值 = mismatch
      ——这是最难也最关键的一类：它在人眼看来很像，
        但在几何上与真实建筑毫无对应关系。文旅内容的事故大多出在这里。
"""
from __future__ import annotations

import sys
import json
import time
import pathlib
import argparse
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.verify import GeoFidelityVerifier, VerifyConfig  # noqa: E402


def build_samples(manifest: dict, variants: list) -> list:
    """把三类样本汇成统一格式：(文件, 声称地点, 参考图列表, 真值, 类别)"""
    samples = []
    for v in variants:
        lid = v["landmark_id"]
        refs = manifest[lid]["reference"]
        samples.append({
            "file": v["file"], "landmark_id": lid, "claim": v["landmark"],
            "references": refs, "truth": "match", "category": "POS",
            "note": v["note"],
        })
    for lid, L in manifest.items():
        for c in L.get("candidate", []):
            cat = "NEG-B" if c["truth"] == "match" else "NEG-A"
            # 关键：AI 重新生成的「同名地点」，真值是 mismatch 而非 match
            truth = "mismatch"
            samples.append({
                "file": c["file"], "landmark_id": lid, "claim": L["name"],
                "references": L["reference"], "truth": truth, "category": cat,
                "note": ("AI 用同名提示词重新生成，非同一物理建筑"
                         if cat == "NEG-B" else c["note"]),
            })

    # NEG-C 跨地标：拿 A 地标的真实参考照，去验 B 地标的图。
    # 这是最基础也必须过的一关——系统若在这上面出错，说明它根本没在比对场景。
    ids = list(manifest.keys())
    for lid in ids:
        for other in ids:
            if other == lid:
                continue
            if not manifest[lid]["reference"]:
                continue
            samples.append({
                "file": manifest[lid]["reference"][0],
                "landmark_id": other, "claim": manifest[other]["name"],
                "references": manifest[other]["reference"],
                "truth": "mismatch", "category": "NEG-C",
                "note": "跨地标：%s 的实照被声称为 %s" % (
                    manifest[lid]["name"], manifest[other]["name"]),
            })
    return samples


def run(detector: str, samples: list, cfg_kw: dict) -> dict:
    cfg = VerifyConfig(detector=detector, **cfg_kw)
    v = GeoFidelityVerifier(cfg, evidence_dir=None)
    rows, dist = [], defaultdict(list)
    t0 = time.time()
    for s in samples:
        r = v.verify(str(ROOT / s["file"]),
                     [str(ROOT / x) for x in s["references"]], s["claim"])
        # 门禁只有通过 / 不通过两种业务后果，needs_human_review 计入不通过
        pred = "match" if r.verdict == "match" else "mismatch"
        rows.append({
            "file": s["file"], "category": s["category"], "claim": s["claim"],
            "truth": s["truth"], "verdict": r.verdict, "pred": pred,
            "inliers": r.best_inliers,
            "inlier_ratio": round(r.evidence[0].inlier_ratio, 4) if r.evidence else 0.0,
            "confidence": round(r.confidence, 3),
            "elapsed_ms": round(r.elapsed_ms, 1),
            "correct": pred == s["truth"],
        })
        dist[s["category"]].append(r.best_inliers)

    tp = sum(1 for r in rows if r["truth"] == "match" and r["pred"] == "match")
    fp = sum(1 for r in rows if r["truth"] == "mismatch" and r["pred"] == "match")
    fn = sum(1 for r in rows if r["truth"] == "match" and r["pred"] == "mismatch")
    tn = sum(1 for r in rows if r["truth"] == "mismatch" and r["pred"] == "mismatch")

    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    acc = (tp + tn) / len(rows) if rows else 0.0

    # 误杀率 = 真样本被拦下的比例；漏放率 = 假样本被放行的比例
    fnr = fn / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0

    return {
        "detector": detector,
        "config": {**{"detector": detector}, **cfg_kw},
        "n_samples": len(rows),
        "confusion_matrix": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
        "metrics": {
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4), "accuracy": round(acc, 4),
            "false_negative_rate_误杀": round(fnr, 4),
            "false_positive_rate_漏放": round(fpr, 4),
        },
        "inlier_distribution": {
            k: {"n": len(v_), "min": min(v_), "max": max(v_),
                "mean": round(sum(v_) / len(v_), 1)}
            for k, v_ in dist.items() if v_
        },
        "mean_latency_ms": round(sum(r["elapsed_ms"] for r in rows) / len(rows), 1) if rows else 0,
        "total_wall_s": round(time.time() - t0, 1),
        "rows": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detectors", nargs="+", default=["AKAZE", "ORB", "SIFT"])
    ap.add_argument("--out", default=str(ROOT / "eval" / "calibration_report.json"))
    a = ap.parse_args()

    manifest = json.loads((ROOT / "assets" / "manifest.json").read_text(encoding="utf-8"))
    variants = json.loads((ROOT / "assets" / "variant" / "variants.json").read_text(encoding="utf-8"))
    samples = build_samples(manifest, variants)

    from collections import Counter
    cnt = Counter(s["category"] for s in samples)
    print("校准集：%d 条  %s\n" % (len(samples), dict(cnt)))

    report = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "sample_count": len(samples), "runs": []}
    for d in a.detectors:
        print("=== %s ===" % d, flush=True)
        r = run(d, samples, {})
        report["runs"].append(r)
        m, c = r["metrics"], r["confusion_matrix"]
        print("  混淆矩阵  TP=%d FP=%d FN=%d TN=%d" % (c["TP"], c["FP"], c["FN"], c["TN"]))
        print("  查准率 %.3f | 查全率 %.3f | F1 %.3f | 准确率 %.3f"
              % (m["precision"], m["recall"], m["f1"], m["accuracy"]))
        print("  误杀率 %.3f | 漏放率 %.3f | 平均耗时 %.1f ms"
              % (m["false_negative_rate_误杀"], m["false_positive_rate_漏放"],
                 r["mean_latency_ms"]))
        for k, v_ in r["inlier_distribution"].items():
            print("  内点分布 %-6s n=%-3d min=%-6d mean=%-8.1f max=%d"
                  % (k, v_["n"], v_["min"], v_["mean"], v_["max"]))
        print()

    pathlib.Path(a.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告 ->", a.out)


if __name__ == "__main__":
    main()
