#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成展示页所需的演示用例：判定结果 + 匹配点连线证据图 + 缩略图。"""
from __future__ import annotations

import sys, json, pathlib, shutil
import cv2

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.verify import GeoFidelityVerifier, VerifyConfig  # noqa: E402

WEB = ROOT / "web" / "media"
WEB.mkdir(parents=True, exist_ok=True)

CASES = [
    dict(id="pos_yuelu", title="同一地点·另一时段拍摄",
         subtitle="岳麓书院 · 黄昏光线 + 视角位移 + 平台压缩",
         candidate="assets/variant/yuelu_academy_b1_v4_dusk.jpg",
         landmark="yuelu_academy", claim="岳麓书院", expect="match",
         why="真实世界里同一个地方的两次拍摄。光线、角度、画质都变了，但建筑的物理结构点没变，所以内点数极高。"),
    dict(id="neg_ai_yuelu", title="AI 重新生成的「岳麓书院」",
         subtitle="同一段提示词再生成一次 · 人眼看着很像",
         candidate="assets/candidate/yuelu_academy_match.jpg",
         landmark="yuelu_academy", claim="岳麓书院", expect="mismatch",
         why="这是整套系统最重要的一个用例。AI 每次生成的「岳麓书院」都是一座全新的建筑——看着像，但它在几何上和真实的岳麓书院毫无对应关系。内点数与一个完全不相干的地方处在同一量级。发出去就是一次文旅事故。"),
    dict(id="neg_desert", title="张冠李戴·完全异景",
         subtitle="西北荒漠烽火台 · 却被声称是天心阁",
         candidate="assets/candidate/tianxin_tower_mismatch.jpg",
         landmark="tianxin_tower", claim="天心阁", expect="mismatch",
         why="最直白的一类造假。系统给出接近零的内点数，且在证据图上找不到任何一条几何自洽的连线。"),
    dict(id="neg_cross", title="跨地标·拿甲地的实照冒充乙地",
         subtitle="太平老街实照 · 却被声称是岳麓书院",
         candidate="assets/reference/taiping_street_ref1.jpg",
         landmark="yuelu_academy", claim="岳麓书院", expect="mismatch",
         why="两张都是真实素材，但不是同一个地方。这一关考的是系统到底有没有在比对场景，而不是在比对「风格像不像」。"),
]


def thumb(src: pathlib.Path, dst: pathlib.Path, w=560):
    im = cv2.imread(str(src))
    if im is None:
        return False
    h = int(im.shape[0] * w / im.shape[1])
    cv2.imwrite(str(dst), cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 78])
    return True


def main():
    manifest = json.loads((ROOT / "assets" / "manifest.json").read_text(encoding="utf-8"))
    v = GeoFidelityVerifier(VerifyConfig(detector="ORB"), evidence_dir=ROOT / "assets" / "evidence")
    out = []
    for c in CASES:
        refs = manifest[c["landmark"]]["reference"]
        r = v.verify(str(ROOT / c["candidate"]), [str(ROOT / x) for x in refs],
                     c["claim"], tag=c["id"])
        d = r.to_dict("full")
        best = max(r.evidence, key=lambda e: e.inliers) if r.evidence else None

        thumb(ROOT / c["candidate"], WEB / ("%s_cand.jpg" % c["id"]))
        thumb(ROOT / refs[0], WEB / ("%s_ref.jpg" % c["id"]))
        ev_name = None
        if best and best.evidence_image:
            src = ROOT / "assets" / "evidence" / pathlib.Path(best.evidence_image).name
            if src.exists():
                ev_name = "%s_evidence.jpg" % c["id"]
                thumb(src, WEB / ev_name, w=1100)

        out.append({
            **{k: c[k] for k in ("id", "title", "subtitle", "claim", "expect", "why")},
            "verdict": r.verdict, "confidence": round(r.confidence, 3),
            "inliers": r.best_inliers,
            "inlier_ratio": round(best.inlier_ratio, 4) if best else 0.0,
            "good_matches": best.good_matches if best else 0,
            "keypoints_query": best.keypoints_query if best else 0,
            "keypoints_reference": best.keypoints_reference if best else 0,
            "elapsed_ms": round(r.elapsed_ms, 1),
            "checkpoints": d["checkpoints"],
            "best_reference": r.best_reference,
            "media": {"candidate": "media/%s_cand.jpg" % c["id"],
                      "reference": "media/%s_ref.jpg" % c["id"],
                      "evidence": ("media/" + ev_name) if ev_name else None},
            "correct": (r.verdict == "match") == (c["expect"] == "match"),
        })
        print("%-14s verdict=%-18s inliers=%-6d %s"
              % (c["id"], r.verdict, r.best_inliers, "OK" if out[-1]["correct"] else "!! 与预期不符"))

    (ROOT / "web" / "demo_cases.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 地标画廊缩略图
    gal = []
    for lid, L in manifest.items():
        if L["reference"]:
            thumb(ROOT / L["reference"][0], WEB / ("lm_%s.jpg" % lid), w=420)
            gal.append({"id": lid, "name": L["name"],
                        "img": "media/lm_%s.jpg" % lid,
                        "refs": len(L["reference"])})
    (ROOT / "web" / "landmarks.json").write_text(
        json.dumps(gal, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n演示用例 -> web/demo_cases.json ；地标 %d 个" % len(gal))


if __name__ == "__main__":
    main()
