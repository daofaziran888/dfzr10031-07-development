"""实验样本分配接口：生成分组名单、查看实验报告、按地区/实验臂聚合与核对曝光。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload
from app.services.experiment_sample import SampleError, service

router = APIRouter(prefix="/api/experiment/{entry_id}/sample", tags=["实验样本分配"])


def _handle(error: SampleError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


@router.get("", response_model=dict)
def get_sample(entry_id: int) -> dict[str, Any]:
    """读取实验样本分配表：分组名单、各臂人数与未加入名单的观测。"""
    try:
        return service.roster(entry_id)
    except SampleError as error:
        raise _handle(error) from error


@router.post("/sync", response_model=ActionResult)
def sync_sample(entry_id: int) -> ActionResult:
    """从来源观测归并同一参与者，生成或刷新分组名单。

    同一参与者的多条记录只进入首次曝光对应的实验臂；已经曝光的参与者
    重新生成时保留原实验臂与启动时地区。
    """
    try:
        summary = service.sync_roster(entry_id)
    except SampleError as error:
        raise _handle(error) from error
    return ActionResult(
        ok=True,
        message=(
            f"分组名单已生成：新增 {summary['created']} 人、刷新 {summary['updated']} 人，"
            f"名单共 {summary['participants']} 人，待归属观测 {summary['unattributed_observations']} 条"
        ),
        entry=summary,
    )


@router.get("/aggregate", response_model=dict)
def aggregate(
    entry_id: int,
    region: str | None = Query(default=None, description="按分层地区筛选"),
    arm: str | None = Query(default=None, description="按实验臂筛选"),
    region_basis: str = Query(default="start", description="start=启动时地区，current=更正后地区"),
) -> dict[str, Any]:
    """按实验样本分配表聚合各臂指标；筛选后的分子、分母和待归属记录同属一次查询范围。"""
    try:
        return service.aggregate(
            entry_id, region=region, arm=arm, region_basis=region_basis
        )
    except SampleError as error:
        raise _handle(error) from error


@router.get("/report", response_model=dict)
def get_report(
    entry_id: int,
    region: str | None = Query(default=None, description="按分层地区筛选"),
    arm: str | None = Query(default=None, description="按实验臂筛选"),
    region_basis: str = Query(default="start", description="start=启动时地区，current=更正后地区"),
) -> dict[str, Any]:
    """实验报告：解释人群口径、样本分母、地区口径与待归属观测。"""
    try:
        return service.report(entry_id, region=region, arm=arm, region_basis=region_basis)
    except SampleError as error:
        raise _handle(error) from error


@router.get("/participants/{participant_id}/reconcile", response_model=dict)
def reconcile(entry_id: int, participant_id: str) -> dict[str, Any]:
    """重新查询关联的历史曝光，核对实际分组与两种地区口径下的分母归属。"""
    try:
        return service.reconcile(entry_id, participant_id)
    except SampleError as error:
        raise _handle(error) from error


@router.get("/observations", response_model=dict)
def list_observations(entry_id: int) -> dict[str, Any]:
    """查看来源观测明细：带参与者编号、观测时间、分组字段与地区。"""
    try:
        entry = service.experiment(entry_id)
    except SampleError as error:
        raise _handle(error) from error
    code = str(entry.get("方案编号") or "").strip()
    items = service._observations(code)  # noqa: SLF001 - 同模块只读视图
    return {"module": "experiment_observation", "total": len(items), "items": items}


@router.post("/observations", response_model=ActionResult)
def add_observation(entry_id: int, payload: EntryPayload) -> ActionResult:
    """补录一条来源观测；同一参与者已有曝光时只追加观测，不会改变其实验臂。"""
    try:
        result = service.add_observation(entry_id, payload.values)
    except SampleError as error:
        raise _handle(error) from error
    return ActionResult(
        ok=True,
        message=(
            f"来源观测已补录：{result['observation']['观测编号']}；"
            f"名单共 {result['summary']['participants']} 人，待归属观测 "
            f"{result['summary']['unattributed_observations']} 条"
        ),
        entry=result["observation"],
    )
