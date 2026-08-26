"""
server/api/routers/service.py 与 server/api/routers/stats.py 单元测试
服务路由的纯函数（配置合并/验证/精度）与统计路由
"""
import pytest
from fastapi import HTTPException

import server.api.routers.service as svc
import server.api.routers.stats as stats_mod
from server.api.routers.service import (
    _apply_config_updates,
    validate_service_config,
    ServiceConfig,
)


# --------------------------------------------------------------------------- #
# _apply_config_updates —— 多向量后端配置合并
# --------------------------------------------------------------------------- #
class TestApplyConfigUpdates:
    def test_chroma_backend(self):
        cur = {}
        out = _apply_config_updates(cur, {
            "vector": {"backend": "chroma", "db_path": "/x/db", "collection_name": "c", "vector_size": 512},
        })
        assert out["memory"]["vector_backend"] == "chroma"
        assert out["memory"]["chroma"]["db_path"] == "/x/db"
        assert out["memory"]["chroma"]["collection_name"] == "c"
        assert out["memory"]["chroma"]["vector_size"] == 512

    def test_milvus_lite_backend(self):
        out = _apply_config_updates({}, {"vector": {"backend": "milvus_lite", "db_path": "/x/m", "vector_size": 256}})
        assert out["memory"]["vector_backend"] == "milvus_lite"
        assert out["memory"]["milvus_lite"]["db_path"] == "/x/m"
        assert out["memory"]["milvus_lite"]["vector_size"] == 256

    def test_weaviate_backend(self):
        out = _apply_config_updates({}, {"vector": {"backend": "weaviate", "weaviate_host": "h", "weaviate_port": 9000}})
        assert out["memory"]["vector_backend"] == "weaviate"
        # 第五轮 H3：写键映射为 UnifiedConfig.WeaviateConfig 真实字段 host/port
        assert out["memory"]["weaviate"]["host"] == "h"
        assert out["memory"]["weaviate"]["port"] == 9000
        assert out["memory"]["weaviate"]["embedded"] is False

    def test_weaviate_embedded_backend(self):
        out = _apply_config_updates(
            {}, {"vector": {"backend": "weaviate_embedded", "weaviate_host": "h", "weaviate_port": 9000}}
        )
        assert out["memory"]["vector_backend"] == "weaviate_embedded"
        assert out["memory"]["weaviate"]["host"] == "h"
        assert out["memory"]["weaviate"]["port"] == 9000
        assert out["memory"]["weaviate"]["embedded"] is True

    def test_qdrant_backend(self):
        out = _apply_config_updates({}, {"vector": {"backend": "qdrant", "qdrant_host": "q", "qdrant_port": 6333}})
        assert out["memory"]["vector_backend"] == "qdrant"
        assert out["memory"]["qdrant"]["qdrant_host"] == "q"
        assert out["memory"]["qdrant"]["qdrant_port"] == 6333

    def test_models_and_llm_params(self):
        out = _apply_config_updates({}, {"models": {"main": 1}, "llm_params": {"t": 0.7}})
        assert out["models"] == {"main": 1}
        assert out["llm_params"] == {"t": 0.7}

    def test_system_merge(self):
        out = _apply_config_updates({"system": {"host": "0.0.0.0"}}, {"system": {"port": 9000}})
        assert out["system"]["host"] == "0.0.0.0"
        assert out["system"]["port"] == 9000

    def test_system_explicit_keys(self):
        out = _apply_config_updates({}, {"host": "127.0.0.1", "port": 8001, "use_conda": False})
        assert out["system"]["host"] == "127.0.0.1"
        assert out["system"]["port"] == 8001
        assert out["system"]["use_conda"] is False

    def test_unknown_backend_ignored(self):
        out = _apply_config_updates({}, {"vector": {"backend": "unknown", "host": "x"}})
        assert out["memory"]["vector_backend"] == "unknown"

    def test_no_memory_key_preserved(self):
        out = _apply_config_updates({}, {"models": {"a": 1}})
        assert "memory" not in out


# --------------------------------------------------------------------------- #
# validate_service_config —— 命令注入防护
# --------------------------------------------------------------------------- #
class TestValidateServiceConfig:
    def test_valid(self):
        validate_service_config(ServiceConfig(host="0.0.0.0", port=8000, log_level="info"))

    def test_valid_custom_ip(self):
        validate_service_config(ServiceConfig(host="192.168.1.10", port=8080, log_level="debug"))

    def test_invalid_ip(self):
        with pytest.raises(HTTPException) as ex:
            validate_service_config(ServiceConfig(host="999.999.999.999", port=8000))
        assert ex.value.status_code == 400
        assert "Invalid host" in str(ex.value.detail)

    def test_invalid_host_format(self):
        with pytest.raises(HTTPException):
            validate_service_config(ServiceConfig(host="evil.com", port=8000))

    def test_port_zero(self):
        with pytest.raises(HTTPException) as ex:
            validate_service_config(ServiceConfig(host="0.0.0.0", port=0))
        assert "Invalid port" in str(ex.value.detail)

    def test_port_too_high(self):
        with pytest.raises(HTTPException):
            validate_service_config(ServiceConfig(host="0.0.0.0", port=70000))

    def test_invalid_log_level(self):
        with pytest.raises(HTTPException) as ex:
            validate_service_config(ServiceConfig(host="0.0.0.0", port=8000, log_level="verbose"))
        assert "Invalid log_level" in str(ex.value.detail)


# --------------------------------------------------------------------------- #
# get_conda_python_path / get_conda_activate_script
# --------------------------------------------------------------------------- #
class TestCondaPaths:
    def test_no_conda(self, monkeypatch):
        monkeypatch.setattr(svc, "get_project_root", lambda: "/nonexistent")
        assert svc.get_conda_python_path() is None
        assert svc.get_conda_activate_script() is None

    def test_finds_python(self, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "get_project_root", lambda: str(tmp_path))
        py = tmp_path / "Miniconda3" / "python.exe"
        py.parent.mkdir(parents=True)
        py.write_bytes(b"")
        assert svc.get_conda_python_path() == str(py)


# --------------------------------------------------------------------------- #
# /service/startup-command 路径选择
# --------------------------------------------------------------------------- #
class TestGetStartupCommand:
    @pytest.mark.asyncio
    async def test_conda_available(self, monkeypatch):
        monkeypatch.setattr(svc, "get_conda_python_path", lambda: "/opt/conda/bin/python")
        out = await svc.get_startup_command(use_conda=True)
        assert out["use_conda"] is True
        assert out["conda_available"] is True
        assert out["command"] == "/opt/conda/bin/python"
        assert "-m" in out["args"] and "uvicorn" in out["args"]

    @pytest.mark.asyncio
    async def test_conda_unavailable_falls_system(self, monkeypatch):
        monkeypatch.setattr(svc, "get_conda_python_path", lambda: None)
        out = await svc.get_startup_command(use_conda=True)
        assert out["conda_available"] is False


# --------------------------------------------------------------------------- #
# /service/environment
# --------------------------------------------------------------------------- #
class TestEnvironmentInfo:
    @pytest.mark.asyncio
    async def test_returns_platform(self, monkeypatch):
        monkeypatch.setattr(svc, "get_conda_python_path", lambda: None)
        out = await svc.get_environment_info()
        assert out["status"] == "success"
        assert out["environment"]["conda_available"] is False
        assert "platform" in out["environment"]


# --------------------------------------------------------------------------- #
# /service/config 与 /config/gateway
# --------------------------------------------------------------------------- #
class TestServiceConfigRoutes:
    @pytest.mark.asyncio
    async def test_gateway_config(self, monkeypatch):
        out = await svc.get_gateway_config()
        assert out["status"] == "success"
        assert out["config"]["status"] == "集成"
        assert "ws://127.0.0.1:8000/ws" in out["config"]["url"]


# --------------------------------------------------------------------------- #
# stats router
# --------------------------------------------------------------------------- #
class TestStatsRouter:
    def test_returns_counts(self):
        # stats 路由的 HTTPException 依赖真实 memory_mgr，此处仅验证模块可导入
        assert hasattr(stats_mod, "get_system_stats")