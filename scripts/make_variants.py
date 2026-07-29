#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
城设 CityBible · 正样本构造器

为什么需要这一步
----------------
判定引擎要回答的是「这张照片拍的是不是同一个物理地点」。要构造出真正的
正样本（同一地点的另一次拍摄），必须保证两张图对应的是同一组物理结构点。

AI 文生图做不到这一点：用同一段提示词生成两次「岳麓书院」，得到的是
两座外观相似但结构不同的建筑。这一现象本身就是本项目存在的理由，
我们把它保留为最难的一类负样本（见 eval/build_calibration.py）。

因此正样本采用 HPatches / Oxford-Affine 数据集的标准做法：
在同一张底图上施加受控的视角变换与光照变换，模拟「换个角度、换个时段
再拍一次同一个地方」。变换参数与真值一并落盘，可复现、可审计。

参考：Balntas et al., "HPatches: A benchmark and evaluation of handcrafted
and learned local descriptors", CVPR 2017.
"""
from __future__ import annotations

import json
import pathlib
import argparse

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent


def perspective_warp(img: np.ndarray, strength: float, seed: int):
    """模拟视点位移：对四角施加受控扰动后做透视变换。"""
    rng = np.random.RandomState(seed)
    h, w = img.shape[:2]
    d = strength * min(h, w)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + rng.uniform(-d, d, src.shape).astype(np.float32)
    # 归一化到原尺寸，避免出现大片黑边
    dst -= dst.min(axis=0)
    sx = w / (dst[:, 0].max() or 1)
    sy = h / (dst[:, 1].max() or 1)
    dst[:, 0] *= sx
    dst[:, 1] *= sy
    M = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
    out = cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REFLECT_101)
    return out, M


def photometric(img: np.ndarray, gain: float, bias: int, warm: float):
    """模拟不同时段/天气的光照与色温差异。"""
    out = cv2.convertScaleAbs(img, alpha=gain, beta=bias)
    b, g, r = cv2.split(out.astype(np.float32))
    r = np.clip(r * (1.0 + warm), 0, 255)
    b = np.clip(b * (1.0 - warm), 0, 255)
    return cv2.merge([b, g, r]).astype(np.uint8)


def recompress(img: np.ndarray, quality: int) -> np.ndarray:
    """模拟经过社交平台压缩后的画质损失。"""
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else img


PRESETS = [
    # name,          视角强度, 增益,  偏置, 色温,  JPEG质量
    ("v1_slight",     0.020, 1.05,   6,  0.04, 92),
    ("v2_moderate",   0.045, 0.92,  -8, -0.05, 85),
    ("v3_strong",     0.075, 1.12,  12,  0.08, 78),
    ("v4_dusk",       0.035, 0.78, -18,  0.14, 88),
    ("v5_overcast",   0.060, 1.02,   2, -0.10, 74),
    ("v6_hard",       0.095, 1.18,  16,  0.06, 68),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(ROOT / "assets" / "manifest.json"))
    ap.add_argument("--out", default=str(ROOT / "assets" / "variant"))
    a = ap.parse_args()

    manifest = json.loads(pathlib.Path(a.manifest).read_text(encoding="utf-8"))
    outdir = pathlib.Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)

    records = []
    for lid, L in manifest.items():
        if not L.get("reference"):
            continue
        for bi, base_rel in enumerate(L["reference"]):
          base = cv2.imread(str(ROOT / base_rel), cv2.IMREAD_COLOR)
          if base is None:
            print("跳过（读不到底图）:", base_rel)
            continue
          for i, (name, s, gain, bias, warm, q) in enumerate(PRESETS):
            warped, M = perspective_warp(base, s, seed=(abs(hash(lid)) % 10000) + i * 7 + bi * 131)
            lit = photometric(warped, gain, bias, warm)
            final = recompress(lit, q)
            fn = "%s_b%d_%s.jpg" % (lid, bi + 1, name)
            cv2.imwrite(str(outdir / fn), final, [cv2.IMWRITE_JPEG_QUALITY, 90])
            records.append({
                "file": "assets/variant/" + fn,
                "landmark_id": lid,
                "landmark": L["name"],
                "derived_from": base_rel,
                "truth": "match",
                "kind": "geometric_photometric_variant",
                "params": {"perspective_strength": s, "gain": gain,
                           "bias": bias, "warmth": warm, "jpeg_quality": q},
                "homography_applied": [[float(x) for x in row] for row in M],
                "note": "同一物理场景的受控视角/光照变换（HPatches 式构造）",
            })
            print("OK", fn)

    (outdir / "variants.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n共生成 %d 张正样本 -> %s" % (len(records), outdir / "variants.json"))


if __name__ == "__main__":
    main()
