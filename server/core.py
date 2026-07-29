#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""城设 CityBible · 核心域逻辑与 MCP 分发（零第三方依赖）

刻意不依赖 FastAPI：
  1) 核心逻辑可在任何环境用标准库直接测试与运行；
  2) server/app.py 与 server/simple_server.py 都只是它的薄封装；
  3) 部署环境装不上 web 框架时，仍有一条能跑通的降级路径。
"""
from __future__ import annotations

import os, sys, json, time, pathlib
from typing import Any, Dict, List, Optional

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.verify import GeoFidelityVerifier, VerifyConfig  # noqa: E402

APP_VERSION = "0.1.0"
TOKEN = os.environ.get("CITYBIBLE_API_TOKEN", "")

MANIFEST: Dict[str, Any] = json.loads(
    (ROOT / "assets" / "manifest.json").read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "web" / "demo_cases.json").read_text(encoding="utf-8"))
CALIB_PATH = ROOT / "eval" / "calibration_report.json"

VERIFIER = GeoFidelityVerifier(
    VerifyConfig(detector=os.environ.get("CITYBIBLE_DETECTOR", "ORB")),
    evidence_dir=ROOT / "runtime" / "evidence")


def landmarks() -> List[Dict[str, Any]]:
    return [{"id": k, "name": v["name"], "reference_count": len(v["reference"])}
            for k, v in MANIFEST.items()]


def resolve(landmark: str) -> Optional[str]:
    if landmark in MANIFEST:
        return landmark
    for k, v in MANIFEST.items():
        if v["name"] == landmark:
            return k
    return None


def do_verify(image_path: str, landmark: str, detail: str = "summary") -> Dict[str, Any]:
    lid = resolve(landmark)
    if lid is None:
        return {"error": "资产库中没有『%s』。已收录：%s"
                         % (landmark, "、".join(v["name"] for v in MANIFEST.values()))}
    if not pathlib.Path(image_path).exists():
        return {"error": "找不到文件: %s" % image_path}
    refs = [str(ROOT / p) for p in MANIFEST[lid]["reference"]]
    return VERIFIER.verify(image_path, refs, MANIFEST[lid]["name"]).to_dict(detail)


def do_query_asset(landmark: str) -> Dict[str, Any]:
    lid = resolve(landmark)
    if lid is None:
        return {"error": "资产库中没有『%s』" % landmark}
    v = MANIFEST[lid]
    return {"id": lid, "name": v["name"],
            "reference_images": v["reference"],
            "reference_count": len(v["reference"]),
            "provenance": "AI 生成的演示素材，自有版权，无第三方版权风险",
            "license": "demo-only",
            "note": "生产环境此处应为多方位多时段的授权实拍素材"}


def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "citybible", "version": APP_VERSION,
            "detector": VERIFIER.cfg.detector, "landmarks": len(MANIFEST),
            "ts": int(time.time())}


def calibration() -> Dict[str, Any]:
    if not CALIB_PATH.exists():
        return {"error": "尚未生成校准报告"}
    d = json.loads(CALIB_PATH.read_text(encoding="utf-8"))
    for run in d.get("runs", []):
        run.pop("rows", None)
    return d


# ------------------------------------------------------------------ MCP

MCP_TOOLS = [
    {
        "name": "verify_geo_fidelity",
        "description": (
            "校验一张图片拍摄的地点是否与声称的地点相符。用于文旅内容发布前的验真："
            "AI 生成的、或张冠李戴的地点图片会被判为 mismatch。"
            "返回 verdict（match/mismatch/needs_human_review）、置信度与证据。"
            "默认返回摘要（约 200 token）；需要完整证据链时传 detail=full。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string",
                               "description": "待验图片的本地绝对路径"},
                "landmark": {"type": "string",
                             "description": "被声称的地点，可用中文名或 id，如「岳麓书院」"},
                "detail": {"type": "string", "enum": ["summary", "full"],
                           "default": "summary",
                           "description": "summary 只回结论，full 附完整证据链"},
            },
            "required": ["image_path", "landmark"],
        },
        "annotations": {"title": "地理真实性验真", "readOnlyHint": True,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "list_landmarks",
        "description": "列出城市素材资产库中已收录的全部地点及其参考照数量。",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"title": "列出已收录地点", "readOnlyHint": True,
                        "idempotentHint": True},
    },
    {
        "name": "query_city_asset",
        "description": "查询某个地点在资产库中的参考素材、数量、来源与授权状态。",
        "inputSchema": {
            "type": "object",
            "properties": {"landmark": {"type": "string", "description": "地点名或 id"}},
            "required": ["landmark"],
        },
        "annotations": {"title": "查询城市素材", "readOnlyHint": True,
                        "idempotentHint": True},
    },
]


def _text(obj) -> Dict[str, Any]:
    return {"content": [{"type": "text",
                         "text": json.dumps(obj, ensure_ascii=False, indent=2)}]}


def mcp_dispatch(body: Dict[str, Any]) -> Dict[str, Any]:
    """处理一条 MCP JSON-RPC 消息。纯函数，便于单测。"""
    rid = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    def ok(result): return {"jsonrpc": "2.0", "id": rid, "result": result}
    def err(code, msg): return {"jsonrpc": "2.0", "id": rid,
                                "error": {"code": code, "message": msg}}

    if method == "initialize":
        return ok({"protocolVersion": "2025-11-25",
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": "citybible", "version": APP_VERSION}})
    if method in ("notifications/initialized", "ping"):
        return ok({})
    if method == "tools/list":
        return ok({"tools": MCP_TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "verify_geo_fidelity":
                r = do_verify(args.get("image_path", ""), args.get("landmark", ""),
                              args.get("detail", "summary"))
                return ok({**_text(r), "isError": "error" in r})
            if name == "list_landmarks":
                return ok(_text({"count": len(MANIFEST), "landmarks": landmarks()}))
            if name == "query_city_asset":
                r = do_query_asset(args.get("landmark", ""))
                return ok({**_text(r), "isError": "error" in r})
        except Exception as e:
            # 不静默兜底：把真实原因回给调用方
            return ok({**_text({"error": "%s: %s" % (type(e).__name__, e)}),
                       "isError": True})
        return err(-32601, "未知工具: %s" % name)
    return err(-32601, "未实现的方法: %s" % method)
