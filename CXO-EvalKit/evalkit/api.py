"""CXO-EvalKit FastAPI 应用。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from evalkit import __version__
from evalkit.config import EvalConfig, load_config
from evalkit.report import read_report, write_report
from evalkit.runner import start_run
from evalkit.store import TERMINAL_STATUSES, EvalStore
from evalkit.suites import list_suites


class RunRequest(BaseModel):
    """POST /api/v1/runs 请求体。"""

    suite: str
    config_overrides: Dict[str, Any] = Field(default_factory=dict)


def create_app(config: Optional[EvalConfig] = None) -> FastAPI:
    """应用工厂，便于测试注入隔离配置。config 为 None 时走 load_config 默认链。"""
    cfg = config if config is not None else load_config(None)
    store = EvalStore(cfg.data_dir)
    app = FastAPI(title="CXO-EvalKit", version=__version__)

    @app.get("/api/v1/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "version": __version__, "suites": list_suites()}

    @app.get("/api/v1/suites")
    def suites() -> Dict[str, Any]:
        return {"suites": list_suites()}

    @app.post("/api/v1/runs", status_code=202)
    def create_run(req: RunRequest) -> Dict[str, Any]:
        try:
            run_id = start_run(store, req.suite, req.config_overrides, base_config=cfg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"run_id": run_id}

    @app.get("/api/v1/runs")
    def runs() -> Dict[str, Any]:
        return {"runs": store.list_runs()}

    @app.get("/api/v1/runs/{run_id}")
    def run_detail(run_id: str) -> Dict[str, Any]:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
        return run

    @app.get("/api/v1/runs/{run_id}/report")
    def run_report(run_id: str) -> Response:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
        content = read_report(cfg.data_dir, run_id)
        if content is None and run.get("status") in TERMINAL_STATUSES:
            # 报告"到达终态即可拉取"：终态 run 报告缺失时现生成；生成失败回退 404
            try:
                write_report(cfg, run_id)
                content = read_report(cfg.data_dir, run_id)
            except Exception:
                content = None
        if content is None:
            raise HTTPException(status_code=404, detail=f"report.md 尚未生成: {run_id}")
        return Response(content=content, media_type="text/markdown; charset=utf-8")

    return app


# uvicorn evalkit.api:app 入口（默认配置链：config.json → 纯默认值）
app = create_app()
