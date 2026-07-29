#!/usr/bin/env python3
"""城设 CityBible — 演示素材生成器

全部素材由 AI 生成，不使用任何第三方版权图片（这是合规声明的依据）。
每个地标生成：2 张参考照（不同角度/光线）+ 1 张同景候选 + 1 张异景候选。

主用火山 Seedream 5.0（用掉 2026-08-02 到期的资源包余额），
MiniMax image-01 作为备选（Token Plan 窗口恢复后可用）。
"""
import os, json, time, pathlib, urllib.request

ARK = os.environ.get("ARK_KEY", "")
MMX = os.environ.get("MINIMAX_KEY", "")
ARK_HOST = "https://ark.cn-beijing.volces.com"
MMX_HOST = "https://api.minimaxi.com"
ROOT = pathlib.Path(__file__).resolve().parent.parent
STAT = {"tokens": 0, "ark": 0, "mmx": 0, "fail": 0}

LANDMARKS = {
    "yuelu_academy": {
        "name": "岳麓书院",
        "base": "中国湖南长沙岳麓山下的古典书院建筑群，青瓦白墙，木质楹联匾额，庭院古樟树，石板路",
        "views": ["正门牌楼正面视角，晨光柔和", "讲堂庭院斜侧视角，黄昏暖光"],
        "match": "书院回廊与天井，白墙黛瓦，柔和日光，游人稀少",
        "mismatch": "江南水乡古镇的白墙黑瓦临水民居，小桥流水，乌篷船停泊",
    },
    "orange_isle": {
        "name": "橘子洲",
        "base": "中国湖南长沙湘江中的狭长江心绿洲，两侧宽阔江面，洲上绿树成荫，远处现代城市天际线",
        "views": ["高空俯瞰狭长江心洲全貌，晴天", "江畔栈道与开阔江面视角，黄昏"],
        "match": "江心洲绿地与江水交界，远处城市轮廓，薄雾天气",
        "mismatch": "北方内陆湖泊中的圆形小岛，芦苇荡环绕，地貌完全不同",
    },
    "tianxin_tower": {
        "name": "天心阁",
        "base": "中国湖南长沙古城墙上的三层重檐古阁楼，红柱灰瓦，飞檐翘角，青砖城墙，周围古树环绕",
        "views": ["阁楼正面全景，蓝天白云", "城墙下仰视阁楼，侧光"],
        "match": "古阁楼与城墙步道，游人视角，多云天光",
        "mismatch": "西北荒漠戈壁中的夯土烽火台残墩，黄土色调，无植被",
    },
    "taiping_street": {
        "name": "太平老街",
        "base": "中国湖南长沙的明清风格商业老街，青石板路面，两侧木构商铺，红灯笼与布幌子",
        "views": ["街道纵深视角，白天人流熙攘", "老街夜晚灯笼点亮，暖色灯光"],
        "match": "老街支巷，青石板与木门板，清晨行人稀少",
        "mismatch": "现代化购物中心玻璃幕墙中庭，自动扶梯与品牌店铺",
    },
}

SUFFIX = "。写实摄影风格，高细节，自然光，画面中不要出现任何文字、标牌文字或水印。"


def _seedream(prompt, out_path):
    body = json.dumps({
        "model": "doubao-seedream-5-0-260128", "prompt": prompt,
        "size": "2k", "response_format": "url", "watermark": False,
        "sequential_image_generation": "disabled",
    }).encode()
    req = urllib.request.Request(
        f"{ARK_HOST}/api/v3/images/generations", data=body,
        headers={"Authorization": f"Bearer {ARK}", "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=240))
    if "data" not in r:
        raise RuntimeError(str(r)[:200])
    STAT["tokens"] += r.get("usage", {}).get("total_tokens", 0)
    urllib.request.urlretrieve(r["data"][0]["url"], out_path)
    STAT["ark"] += 1
    return "seedream"


def _minimax(prompt, out_path):
    body = json.dumps({
        "model": "image-01", "prompt": prompt, "aspect_ratio": "16:9",
        "n": 1, "response_format": "url",
    }).encode()
    req = urllib.request.Request(
        f"{MMX_HOST}/v1/image_generation", data=body,
        headers={"Authorization": f"Bearer {MMX}", "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=240))
    if r.get("base_resp", {}).get("status_code") != 0:
        raise RuntimeError(str(r.get("base_resp"))[:200])
    urllib.request.urlretrieve(r["data"]["image_urls"][0], out_path)
    STAT["mmx"] += 1
    return "minimax"


def gen(prompt, out_path):
    if out_path.exists() and out_path.stat().st_size > 10000:
        print("  = %s (已存在，跳过)" % out_path.name, flush=True)
        return True
    prompt = prompt + SUFFIX
    for provider, fn, key in (("seedream", _seedream, ARK), ("minimax", _minimax, MMX)):
        if not key:
            continue
        for attempt in range(2):
            try:
                who = fn(prompt, out_path)
                print("  OK %s  [%s]  累计 %d tok" % (out_path.name, who, STAT["tokens"]), flush=True)
                return True
            except Exception as e:
                print("  ! %s 第%d次: %s" % (provider, attempt + 1, str(e)[:130]), flush=True)
                time.sleep(5)
    STAT["fail"] += 1
    return False


def main():
    manifest = {}
    for lid, L in LANDMARKS.items():
        print("\n[%s]" % L["name"], flush=True)
        entry = {"id": lid, "name": L["name"], "reference": [], "candidate": []}
        for i, v in enumerate(L["views"]):
            p = ROOT / "assets" / "reference" / ("%s_ref%d.jpg" % (lid, i + 1))
            if gen("%s，%s" % (L["base"], v), p):
                entry["reference"].append("assets/reference/" + p.name)
        p = ROOT / "assets" / "candidate" / ("%s_match.jpg" % lid)
        if gen("%s，%s" % (L["base"], L["match"]), p):
            entry["candidate"].append({
                "file": "assets/candidate/" + p.name, "truth": "match",
                "claim": L["name"], "note": "同一地点的另一视角"})
        p = ROOT / "assets" / "candidate" / ("%s_mismatch.jpg" % lid)
        if gen(L["mismatch"], p):
            entry["candidate"].append({
                "file": "assets/candidate/" + p.name, "truth": "mismatch",
                "claim": L["name"], "note": "张冠李戴：实为其他地点，却被声称是" + L["name"]})
        manifest[lid] = entry

    (ROOT / "assets" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDONE  seedream=%d minimax=%d fail=%d tokens=%d"
          % (STAT["ark"], STAT["mmx"], STAT["fail"], STAT["tokens"]), flush=True)


if __name__ == "__main__":
    main()
