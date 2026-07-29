#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
城设 CityBible · 后端服务

三层对外形态，一份实现：
  · REST      /api/*      给人和常规客户端，FastAPI 自动出 OpenAPI 文档
  · MCP       /mcp        给任何支持 MCP 的 Agent（Streamable HTTP 单端点）
  · CLI       cli/citybible.py  给终端与断网降级场景

MCP 传输选 Streamable HTTP 而非 stdio 或已废弃的 HTTP+SSE，理由：
MCP 规范自 2025-03-26 起用 Streamable HTTP 取代 HTTP+SSE；火山方舟
Responses API 与 Google Gemini API 均只支持 Streamable HTTP。
"""
from __future__ import annotations

import os
import json
import time
import shutil
import pathlib
import tempfile
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server import core  # noqa: E402

APP_VERSION = core.APP_VERSION

app = FastAPI(
    title="城设 CityBible API", version=APP_VERSION,
    description="城市文旅内容的地理真实性验真门禁。主判定零大模型，结论绑定证据。",
    docs_url="/api/docs", openapi_url="/api/openapi.json")

if (ROOT / "web" / "media").is_dir():
    app.mount("/media", StaticFiles(directory=str(ROOT / "web" / "media")), name="media")


@app.get("/api/health", summary="健康检查")
def health():
    return core.health()


@app.get("/api/landmarks", summary="列出资产库中已收录的地点")
def landmarks():
    return {"count": len(core.MANIFEST), "landmarks": core.landmarks()}


@app.get("/api/asset", summary="查询某地点的素材与授权状态")
def asset(landmark: str):
    r = core.do_query_asset(landmark)
    if "error" in r:
        raise HTTPException(404, r["error"])
    return r


@app.get("/api/cases", summary="演示用例的判定结果（预跑）")
def cases():
    return core.CASES


@app.get("/api/calibration", summary="裁判校准报告")
def calibration():
    r = core.calibration()
    if "error" in r:
        raise HTTPException(404, r["error"])
    return r


@app.post("/api/verify", summary="上传一张图，验证它拍的地点是否与声称相符")
async def verify(file: UploadFile = File(...), landmark: str = Form(...),
                 detail: str = Form("full")):
    suffix = pathlib.Path(file.filename or "x.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as t:
        shutil.copyfileobj(file.file, t)
        tmp = t.name
    try:
        r = core.do_verify(tmp, landmark, detail)
        if "error" in r:
            raise HTTPException(404, r["error"])
        return r
    finally:
        os.unlink(tmp)


@app.post("/mcp", summary="MCP Streamable HTTP 端点")
async def mcp(request: Request):
    # 规范要求：校验 Origin 以防 DNS rebinding
    origin = request.headers.get("origin")
    if origin and not (origin.startswith("http://127.0.0.1")
                       or origin.startswith("http://localhost")):
        raise HTTPException(403, "Origin 未被允许")
    if core.TOKEN and request.headers.get("authorization", "") != "Bearer " + core.TOKEN:
        raise HTTPException(401, "缺少或错误的 Authorization")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "JSON 解析失败"}},
                            status_code=400)
    return core.mcp_dispatch(body)


@app.get("/", include_in_schema=False)
def index():
    f = ROOT / "web" / "index.html"
    return FileResponse(str(f)) if f.exists() else {"service": "citybible", "docs": "/docs"}
