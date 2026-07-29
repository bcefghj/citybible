#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城设 CityBible · 命令行工具

同一套引擎的第三种形态。它同时是断网/平台故障时的降级路径——
演示现场如果网络或第三方平台出问题，这条命令仍然能完整跑出结果。

  citybible landmarks
  citybible asset 岳麓书院
  citybible verify photo.jpg --claim 岳麓书院 [--format json|human] [--evidence out/]
"""
from __future__ import annotations
import sys, json, pathlib, argparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.verify import GeoFidelityVerifier, VerifyConfig  # noqa: E402

MAN = json.loads((ROOT / "assets" / "manifest.json").read_text(encoding="utf-8"))
G, R, Y, B, N = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m"


def resolve(x):
    if x in MAN:
        return x
    for k, v in MAN.items():
        if v["name"] == x:
            return k
    return None


def cmd_landmarks(a):
    print("%s城市素材资产库%s  共 %d 个地点\n" % (B, N, len(MAN)))
    for k, v in MAN.items():
        print("  %-18s %-10s %d 张参考照" % (k, v["name"], len(v["reference"])))


def cmd_asset(a):
    lid = resolve(a.landmark)
    if not lid:
        print("%s找不到：%s%s" % (R, a.landmark, N)); sys.exit(1)
    v = MAN[lid]
    print("%s%s%s  (%s)" % (B, v["name"], N, lid))
    print("  参考照 %d 张：" % len(v["reference"]))
    for p in v["reference"]:
        print("    " + p)
    print("  来源：AI 生成的演示素材，自有版权")


def cmd_verify(a):
    lid = resolve(a.claim)
    if not lid:
        print("%s资产库中没有『%s』。已收录：%s%s"
              % (R, a.claim, "、".join(v["name"] for v in MAN.values()), N)); sys.exit(1)
    refs = [str(ROOT / p) for p in MAN[lid]["reference"]]
    v = GeoFidelityVerifier(VerifyConfig(detector=a.detector), a.evidence)
    r = v.verify(a.image, refs, MAN[lid]["name"])

    if a.format == "json":
        print(json.dumps(r.to_dict("full"), ensure_ascii=False, indent=2)); return

    color = {"match": G, "mismatch": R}.get(r.verdict, Y)
    label = {"match": "通过  MATCH", "mismatch": "打回  MISMATCH",
             "needs_human_review": "转人工复核", "error": "错误"}[r.verdict]
    best = max(r.evidence, key=lambda e: e.inliers) if r.evidence else None
    print("\n  待验图    %s" % a.image)
    print("  声称地点  %s" % MAN[lid]["name"])
    print("  判定      %s%s%s   置信度 %.3f" % (color, label, N, r.confidence))
    if best:
        print("  最佳参考  %s" % best.reference)
        print("  关键点 %d / ratio test 通过 %d / %sRANSAC 内点 %d%s / 内点率 %.1f%%"
              % (best.keypoints_query, best.good_matches, color, best.inliers, N,
                 best.inlier_ratio * 100))
    print("  耗时      %.0f ms\n" % r.elapsed_ms)
    for c in r.checkpoints:
        m = {True: G + "PASS" + N, False: R + "FAIL" + N}.get(c["passed"], Y + "INFO" + N)
        print("    [%s] %-8s %-28s %s" % (m, c["id"], c["name"][:28], c["value"]))
    if best and best.evidence_image:
        print("\n  证据图    %s" % best.evidence_image)
    if r.error:
        print("\n  %s%s%s" % (R, r.error, N))
    print()
    sys.exit(0 if r.verdict == "match" else 2)


def main():
    ap = argparse.ArgumentParser(prog="citybible", description="城设 · 地理真实性验真")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("landmarks", help="列出已收录地点").set_defaults(f=cmd_landmarks)
    p = sub.add_parser("asset", help="查询某地点素材"); p.add_argument("landmark"); p.set_defaults(f=cmd_asset)
    p = sub.add_parser("verify", help="验证一张图")
    p.add_argument("image"); p.add_argument("--claim", required=True)
    p.add_argument("--detector", default="ORB", choices=["ORB", "AKAZE", "SIFT"])
    p.add_argument("--format", default="human", choices=["human", "json"])
    p.add_argument("--evidence", default=None, help="证据图输出目录")
    p.set_defaults(f=cmd_verify)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
