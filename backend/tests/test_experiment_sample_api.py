"""智能告警接口冒烟测试：探针只读、健康检查与样本分配路由挂载。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.store import store

client = TestClient(app)


def setup_function() -> None:
    store.reset()


def test_health_lists_all_modules() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    # 样本分配与来源观测挂在分析实验下面，不额外算作独立业务模块。
    assert response.json()["modules"] == len(store.module_names()) == 18


def test_sample_routes_are_mounted() -> None:
    response = client.get("/api/experiment/3/sample")
    assert response.status_code == 200
    assert response.json()["count"] == 9


def test_sync_endpoint_is_idempotent() -> None:
    first = client.post("/api/experiment/3/sample/sync")
    second = client.post("/api/experiment/3/sample/sync")
    assert first.status_code == 200 and first.json()["ok"] is True
    assert second.json()["entry"]["participants"] == 9
    assert second.json()["entry"]["created"] == 0


def test_draft_experiment_cannot_generate_roster() -> None:
    response = client.post("/api/experiment/1/sample/sync")
    assert response.status_code == 400
    assert "草稿" in response.json()["detail"]


def test_aggregate_rejects_unknown_region_basis() -> None:
    response = client.get("/api/experiment/3/sample/aggregate?region_basis=guess")
    assert response.status_code == 400
    assert "地区口径" in response.json()["detail"]


def test_missing_participant_reconcile_returns_404() -> None:
    response = client.get("/api/experiment/3/sample/participants/PART-9999/reconcile")
    assert response.status_code == 404
