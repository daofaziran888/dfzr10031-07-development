"""实验样本分配业务规则。

把来源数据里同一参与者的多条观测归并成一张分组名单（实验样本分配表），
并给实验报告、OLAP 聚合和曝光核对提供统一的人群口径与地区口径。

不随来源补正改变的原则：

* 一名参与者在一次实验里只占名单中的一行，只进入首次曝光对应的实验臂；
* 曝光已经发生就按实际收到的实验臂归属，后续记录不能改分组；
* 启动时地区取自首次曝光观测，用来复验原分层设计；更正后地区取自最新
  来源观测，用来回答当前地区的响应差异；
* 未进入名单的观测单列，永远不进入任何实验臂的分子或分母。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

SAMPLE_MODULE = "experiment_sample"
OBSERVATION_MODULE = "experiment_observation"
EXPERIMENT_MODULE = "experiment"

DEFAULT_ARMS = ["对照组", "实验组"]
REGION_BASES = {"start": "启动时地区", "current": "更正后地区"}
EXPOSURE_EVENT = "曝光"
GENERATABLE_STATUSES = ["已设计", "运行中", "已完成"]

POPULATION_DEFINITION = (
    "实验人群为实验窗口内至少有一条曝光记录、并因此进入分组名单的参与者；"
    "同一参与者的多条观测先按参与者编号归并，再按首次曝光记录进入且只进入一个实验臂。"
)
DENOMINATOR_DEFINITION = (
    "分母为本次查询范围内分组名单上的去重参与人数；同一参与者只按首次曝光所属实验臂计入一次，"
    "已发生的曝光不会因为后续来源记录或地区更正而改臂。"
)
NUMERATOR_DEFINITION = (
    "分子为分母中至少有一条转化观测的参与人数；转化观测按名单实验臂归属，"
    "不按来源记录里的分组字段重复计入，因此同一次观测不会同时落入两个实验臂。"
)
PENDING_RULE = (
    "未加入名单的观测（没有曝光记录、或没有分组字段的参与者）单列，不进入任何实验臂的分子或分母；"
    "按地区筛选时，待归属记录与分子、分母使用同一地区口径和同一次查询的人群范围。"
)
EXPOSURE_RULE = (
    "已经发生的曝光始终归入实际收到的实验臂：以实验窗口内首次曝光记录的分组字段为准，"
    "后续观测、冲突的分组字段或地区更正只用于核对，不重新分组。"
)


class SampleError(Exception):
    """样本分配相关的可读业务错误。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "yes", "y", "t", "是", "已转化"}


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _time_key(row: dict[str, Any]) -> tuple[datetime, int]:
    return (_parse_time(row.get("观测时间")) or datetime.min, int(row.get("id", 0)))


def _arm(row: dict[str, Any]) -> str:
    return _text(row.get("分组字段"))


def _region(row: dict[str, Any]) -> str:
    return _text(row.get("地区"))


def _is_exposure(row: dict[str, Any]) -> bool:
    event = _text(row.get("事件类型"))
    if event:
        return event == EXPOSURE_EVENT
    return bool(_arm(row))


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


class SampleService:
    """实验样本分配、聚合与核对。"""

    # ------------------------------------------------------------------ 基础读取
    def experiment(self, entry_id: int) -> dict[str, Any]:
        entry = store.find(EXPERIMENT_MODULE, entry_id)
        if entry is None:
            raise SampleError(f"实验方案 {entry_id} 不存在或已归档", status_code=404)
        return entry

    def _code(self, entry: dict[str, Any]) -> str:
        return _text(entry.get("方案编号"))

    def _observations(self, code: str) -> list[dict[str, Any]]:
        rows = [row for row in store.rows(OBSERVATION_MODULE) if _text(row.get("实验编号")) == code]
        return sorted(rows, key=_time_key)

    def _roster(self, code: str) -> list[dict[str, Any]]:
        return [row for row in store.rows(SAMPLE_MODULE) if _text(row.get("实验编号")) == code]

    def _participant_rows(
        self, observations: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in observations:
            participant = _text(row.get("参与者编号"))
            if participant:
                grouped.setdefault(participant, []).append(row)
        return grouped

    # ------------------------------------------------------------------ 名单生成
    def sync_roster(self, entry_id: int) -> dict[str, Any]:
        """按来源观测归并同一参与者，生成或刷新实验样本分配表。

        已曝光参与者一旦进入名单，实验臂与启动时地区不再改变；重复执行只
        刷新观测条数、转化标记和更正后地区，保证历史分组可复验。
        """
        entry = self.experiment(entry_id)
        status = _text(entry.get("status"))
        if status not in GENERATABLE_STATUSES:
            raise SampleError(
                f"实验方案当前状态为「{status or '未设置'}」，需先提交设计才能生成分组名单"
            )
        code = self._code(entry)
        observations = self._observations(code)
        grouped = self._participant_rows(observations)
        all_roster_rows = store.rows(SAMPLE_MODULE)
        roster_rows = [
            row for row in all_roster_rows if _text(row.get("实验编号")) == code
        ]
        existing = {_text(row.get("参与者编号")): row for row in roster_rows}
        next_id = max((int(row.get("id", 0)) for row in all_roster_rows), default=0) + 1
        created = 0
        updated = 0
        for participant, rows in grouped.items():
            ordered = sorted(rows, key=_time_key)
            arms_seen = _ordered_unique([_arm(row) for row in ordered])
            exposure_rows = [row for row in ordered if _is_exposure(row)]
            armed_exposures = [row for row in exposure_rows if _arm(row)]
            if armed_exposures:
                entry_row: dict[str, Any] | None = armed_exposures[0]
            else:
                # 曝光记录没带分组字段、或事件类型未标注时，不能被认定为进入
                # 某个实验臂；这类参与者保持待归属，不猜实验臂。
                entry_row = next(
                    (
                        row
                        for row in ordered
                        if _arm(row) and not _text(row.get("事件类型"))
                    ),
                    None,
                )
            if entry_row is None:
                # 没有可认定的曝光分组：参与者没有进入实验，观测保持待归属。
                continue

            row = existing.get(participant)
            if row is None:
                start_region = _region(entry_row) or next(
                    (_region(item) for item in ordered if _region(item)), "未标注"
                )
                row = {
                    "id": next_id,
                    "实验编号": code,
                    "参与者编号": participant,
                    "实验臂": _arm(entry_row),
                    "启动时地区": start_region,
                    "首次曝光时间": _text(entry_row.get("观测时间")),
                }
                next_id += 1
                all_roster_rows.append(row)
                roster_rows.append(row)
                existing[participant] = row
                created += 1
            else:
                updated += 1

            current_region = next(
                (_region(item) for item in reversed(ordered) if _region(item)),
                _text(row.get("启动时地区")) or "未标注",
            )
            arms_for_check = set(arms_seen)
            arm = _text(row.get("实验臂"))
            if not arm:
                arm = _arm(entry_row)
                row["实验臂"] = arm
            conflict = len(arms_for_check) > 1 or (bool(arms_for_check) and arm not in arms_for_check)

            row["启动时地区"] = _text(row.get("启动时地区")) or _region(entry_row) or "未标注"
            row["更正后地区"] = current_region
            row["首次曝光时间"] = _text(row.get("首次曝光时间")) or _text(entry_row.get("观测时间"))
            row["最近观测时间"] = _text(ordered[-1].get("观测时间"))
            row["观测条数"] = len(ordered)
            row["曝光条数"] = len(exposure_rows)
            row["分组字段记录数"] = sum(1 for item in ordered if _arm(item))
            row["转化"] = any(_as_bool(item.get("转化")) for item in ordered)
            row["地区已更正"] = _text(row["启动时地区"]) != current_region
            row["分组冲突"] = conflict
            row["状态"] = "已加入名单"
            row["pending"] = False
            row["abnormal"] = bool(conflict or row["地区已更正"])

        summary = self.summary(code)
        summary.update({"created": created, "updated": updated})
        return summary

    # ------------------------------------------------------------------ 汇总
    def summary(self, code: str) -> dict[str, Any]:
        roster = self._roster(code)
        observations = self._observations(code)
        rostered = {_text(row.get("参与者编号")) for row in roster}
        pending = [row for row in observations if _text(row.get("参与者编号")) not in rostered]
        arms = _ordered_unique([_text(row.get("实验臂")) for row in roster])
        arm_totals = {arm: sum(1 for row in roster if _text(row.get("实验臂")) == arm) for arm in arms}
        return {
            "实验编号": code,
            "participants": len(roster),
            "observations": len(observations),
            "arms": arms,
            "arm_participants": arm_totals,
            "converted_participants": sum(1 for row in roster if _as_bool(row.get("转化"))),
            "unattributed_observations": len(pending),
            "corrected_participants": [
                _text(row.get("参与者编号")) for row in roster if _as_bool(row.get("地区已更正"))
            ],
            "conflict_participants": [
                _text(row.get("参与者编号")) for row in roster if _as_bool(row.get("分组冲突"))
            ],
        }

    def roster(self, entry_id: int) -> dict[str, Any]:
        entry = self.experiment(entry_id)
        code = self._code(entry)
        roster = sorted(self._roster(code), key=lambda row: _text(row.get("参与者编号")))
        observations = self._observations(code)
        rostered = {_text(row.get("参与者编号")) for row in roster}
        pending = [
            self._pending_item(row)
            for row in observations
            if _text(row.get("参与者编号")) not in rostered
        ]
        return {
            "experiment": entry,
            "module": SAMPLE_MODULE,
            "count": len(roster),
            "participants": roster,
            "summary": self.summary(code),
            "unattributed_observations": pending,
            "definitions": self.definitions(),
        }

    def _pending_item(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "观测编号": _text(row.get("观测编号")),
            "参与者编号": _text(row.get("参与者编号")),
            "观测时间": _text(row.get("观测时间")),
            "地区": _region(row) or "未标注",
            "分组字段": _arm(row),
            "转化": _as_bool(row.get("转化")),
            "归属原因": "参与者没有曝光记录或没有分组字段，未进入分组名单",
        }

    def definitions(self) -> dict[str, Any]:
        return {
            "population": POPULATION_DEFINITION,
            "denominator": DENOMINATOR_DEFINITION,
            "numerator": NUMERATOR_DEFINITION,
            "pending": PENDING_RULE,
            "exposure": EXPOSURE_RULE,
            "region_bases": REGION_BASES,
        }

    # ------------------------------------------------------------------ 来源观测
    def add_observation(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any]:
        entry = self.experiment(entry_id)
        status = _text(entry.get("status"))
        if status not in GENERATABLE_STATUSES:
            raise SampleError(
                f"实验方案当前状态为「{status or '未设置'}」，需先提交设计才能补录来源观测"
            )
        missing = [
            field for field in ["参与者编号", "观测时间"] if not _text(values.get(field))
        ]
        if missing:
            raise SampleError(f"缺少必填字段：{'、'.join(missing)}")
        observed_at = _parse_time(values.get("观测时间"))
        if observed_at is None:
            raise SampleError("观测时间需为可解析的日期时间，例如 2026-10-09T09:30")
        code = self._code(entry)
        rows = store.rows(OBSERVATION_MODULE)
        arm = _text(values.get("分组字段"))
        event = _text(values.get("事件类型"))
        if not event:
            event = EXPOSURE_EVENT if arm else "观测"
        observation = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "实验编号": code,
            "观测编号": _text(values.get("观测编号"))
            or f"OBSV-{len([row for row in rows if _text(row.get('实验编号')) == code]) + 1:04d}",
            "参与者编号": _text(values.get("参与者编号")),
            "观测时间": _text(values.get("观测时间")),
            "分组字段": arm,
            "地区": _text(values.get("地区")),
            "转化": _as_bool(values.get("转化")),
            "事件类型": event,
            "来源": _text(values.get("来源")) or "来源数据补录",
        }
        rows.append(observation)
        summary = self.sync_roster(entry_id)
        return {"observation": observation, "summary": summary}

    # ------------------------------------------------------------------ OLAP 聚合
    def _basis_field(self, region_basis: str) -> str:
        if region_basis not in REGION_BASES:
            raise SampleError("地区口径只支持 start（启动时地区）或 current（更正后地区）")
        return REGION_BASES[region_basis]

    def aggregate(
        self,
        entry_id: int,
        *,
        region: str | None = None,
        arm: str | None = None,
        region_basis: str = "start",
    ) -> dict[str, Any]:
        entry = self.experiment(entry_id)
        code = self._code(entry)
        basis_field = self._basis_field(region_basis)
        region = _text(region) or None
        arm = _text(arm) or None
        roster = sorted(self._roster(code), key=lambda row: _text(row.get("参与者编号")))
        observations = self._observations(code)

        observations_by_participant: dict[str, list[dict[str, Any]]] = {}
        for row in observations:
            observations_by_participant.setdefault(_text(row.get("参与者编号")), []).append(row)

        scoped = [row for row in roster if not region or _text(row.get(basis_field)) == region]
        all_arms = _ordered_unique([_text(row.get("实验臂")) for row in scoped])
        arms = [value for value in all_arms if not arm or value == arm]

        cells: list[dict[str, Any]] = []
        regions = _ordered_unique([_text(row.get(basis_field)) or "未标注" for row in scoped])
        for region_value in sorted(regions):
            for arm_value in arms:
                members = [
                    row
                    for row in scoped
                    if (_text(row.get(basis_field)) or "未标注") == region_value
                    and _text(row.get("实验臂")) == arm_value
                ]
                if not members:
                    # 没有名单参与者的地区×实验臂组合不占一行，避免把空分母当成观测结果。
                    continue
                denominator = len(members)
                numerator = sum(1 for row in members if _as_bool(row.get("转化")))
                cells.append({
                    "地区": region_value,
                    "实验臂": arm_value,
                    "分母": denominator,
                    "分子": numerator,
                    "转化率": _rate(numerator, denominator),
                    "关联观测数": sum(
                        len(observations_by_participant.get(_text(row.get("参与者编号")), []))
                        for row in members
                    ),
                })

        arm_totals = [
            {
                "实验臂": arm_value,
                "分母": sum(1 for row in scoped if _text(row.get("实验臂")) == arm_value),
                "分子": sum(
                    1
                    for row in scoped
                    if _text(row.get("实验臂")) == arm_value and _as_bool(row.get("转化"))
                ),
                "关联观测数": sum(
                    len(observations_by_participant.get(_text(row.get("参与者编号")), []))
                    for row in scoped
                    if _text(row.get("实验臂")) == arm_value
                ),
            }
            for arm_value in arms
        ]
        for total in arm_totals:
            total["转化率"] = _rate(int(total["分子"]), int(total["分母"]))

        rostered = {_text(row.get("参与者编号")) for row in roster}
        pending_all = [
            row for row in observations if _text(row.get("参与者编号")) not in rostered
        ]
        pending_scoped = [
            row for row in pending_all if not region or (_region(row) or "未标注") == region
        ]
        pending_items = [self._pending_item(row) for row in pending_scoped]
        pending_regions = _ordered_unique([_region(row) or "未标注" for row in pending_scoped])
        pending_summary = [
            {
                "地区": region_value,
                "观测数": sum(
                    1 for row in pending_scoped if (_region(row) or "未标注") == region_value
                ),
                "转化观测数": sum(
                    1
                    for row in pending_scoped
                    if (_region(row) or "未标注") == region_value and _as_bool(row.get("转化"))
                ),
            }
            for region_value in sorted(pending_regions)
        ]

        denominator = sum(int(cell["分母"]) for cell in cells)
        numerator = sum(int(cell["分子"]) for cell in cells)
        return {
            "experiment": entry,
            "module": SAMPLE_MODULE,
            "filters": {
                "地区": region,
                "实验臂": arm,
                "region_basis": region_basis,
                "地区口径": basis_field,
                "arm_filter_applies_to_pending": False,
            },
            "scope": self._scope_text(region, arm, basis_field, denominator, len(pending_scoped)),
            "definitions": self.definitions(),
            "cells": cells,
            "arm_totals": arm_totals,
            "totals": {
                "分母": denominator,
                "分子": numerator,
                "转化率": _rate(numerator, denominator),
                "待归属观测": len(pending_items),
            },
            "pending_observations": pending_items,
            "pending_summary": pending_summary,
            "notes": self._aggregate_notes(region, arm, basis_field),
        }

    def _scope_text(
        self,
        region: str | None,
        arm: str | None,
        basis_field: str,
        denominator: int,
        pending: int,
    ) -> str:
        parts = []
        if region:
            parts.append(f"地区={region}（{basis_field}）")
        if arm:
            parts.append(f"实验臂={arm}")
        scope = "；".join(parts) if parts else "全部名单参与者"
        return (
            f"本次查询人群范围：{scope}。分母 {denominator} 人、待归属观测 {pending} 条"
            f"都按这一次查询的范围计算；实验臂筛选不适用于没有实验臂的待归属观测。"
        )

    def _aggregate_notes(
        self, region: str | None, arm: str | None, basis_field: str
    ) -> list[str]:
        notes = [
            "分子与分母都来自实验样本分配表；同一参与者只按首次曝光所属实验臂计入一次。",
            "来源记录里与名单不一致的分组字段不会把同一次观测分配到另一个实验臂。",
            f"地区筛选使用{basis_field}；切换到另一地区口径会得到同一批参与者的另一种分层结果。",
        ]
        if region:
            notes.append(
                f"待归属观测按来源观测自身的地区纳入「{region}」范围，"
                "与名单参与者使用同一次查询的人群范围，但不会补进任何实验臂。"
            )
        if arm:
            notes.append("待归属观测没有实验臂，实验臂筛选不对其生效，仍在同一地区范围内单列。")
        return notes

    # ------------------------------------------------------------------ 实验报告
    def report(
        self,
        entry_id: int,
        *,
        region: str | None = None,
        arm: str | None = None,
        region_basis: str = "start",
    ) -> dict[str, Any]:
        entry = self.experiment(entry_id)
        code = self._code(entry)
        self._basis_field(region_basis)
        aggregate = self.aggregate(
            entry_id, region=region, arm=arm, region_basis=region_basis
        )
        roster = self._roster(code)
        observations = self._observations(code)
        rostered = {_text(row.get("参与者编号")) for row in roster}
        basis_field = REGION_BASES[region_basis]
        region = _text(region) or None
        arm = _text(arm) or None

        def in_scope_pending(row: dict[str, Any]) -> bool:
            return _text(row.get("参与者编号")) not in rostered and (
                not region or (_region(row) or "未标注") == region
            )

        scoped_pending = [row for row in observations if in_scope_pending(row)]
        no_exposure_participants = _ordered_unique(
            [_text(row.get("参与者编号")) for row in scoped_pending if _text(row.get("参与者编号"))]
        )
        start_strata = self._strata(roster, "启动时地区")
        current_strata = self._strata(roster, "更正后地区")
        return {
            "experiment": entry,
            "module": SAMPLE_MODULE,
            "filters": aggregate["filters"],
            "scope": aggregate["scope"],
            "population": {
                "definition": POPULATION_DEFINITION,
                "sample_scope": _text(entry.get("样本范围")) or "未登记样本范围",
                "grouping_field": _text(entry.get("分组字段")) or "未登记分组字段",
                "included_participants": aggregate["totals"]["分母"],
                "roster_participants": len(roster),
                "excluded_participants": len(no_exposure_participants),
                "excluded_participant_ids": sorted(no_exposure_participants),
                "excluded_observations": aggregate["totals"]["待归属观测"],
                "exclusion_reason": "没有曝光记录或没有分组字段，无法确认实际收到的实验臂",
                "counts_use_query_scope": bool(region),
                "region_basis": region_basis,
                "region_label": basis_field,
            },
            "denominator": {
                "definition": DENOMINATOR_DEFINITION,
                "total": aggregate["totals"]["分母"],
                "by_arm": aggregate["arm_totals"],
                "by_region_arm": aggregate["cells"],
                "region_basis": aggregate["filters"]["region_basis"],
                "region_label": aggregate["filters"]["地区口径"],
            },
            "numerator": {
                "definition": NUMERATOR_DEFINITION,
                "total": aggregate["totals"]["分子"],
            },
            "pending": {
                "definition": PENDING_RULE,
                "observations": aggregate["pending_observations"],
                "summary": aggregate["pending_summary"],
            },
            "strata": {
                "start": {
                    "label": "启动时地区（用于复验原分层设计）",
                    "cells": start_strata,
                },
                "current": {
                    "label": "更正后地区（用于回答当前地区的响应差异）",
                    "cells": current_strata,
                },
            },
            "corrected_participants": [
                {
                    "参与者编号": _text(row.get("参与者编号")),
                    "实验臂": _text(row.get("实验臂")),
                    "启动时地区": _text(row.get("启动时地区")),
                    "更正后地区": _text(row.get("更正后地区")),
                    "首次曝光时间": _text(row.get("首次曝光时间")),
                }
                for row in roster
                if _as_bool(row.get("地区已更正"))
            ],
            "conflict_participants": [
                {
                    "参与者编号": _text(row.get("参与者编号")),
                    "实验臂": _text(row.get("实验臂")),
                    "分组字段记录数": row.get("分组字段记录数", 0),
                }
                for row in roster
                if _as_bool(row.get("分组冲突"))
            ],
            "exposure_rule": EXPOSURE_RULE,
            "notes": aggregate["notes"],
        }

    def _strata(self, roster: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
        arms = _ordered_unique([_text(row.get("实验臂")) for row in roster])
        regions = sorted(_ordered_unique([_text(row.get(field)) or "未标注" for row in roster]))
        cells: list[dict[str, Any]] = []
        for region_value in regions:
            for arm_value in arms:
                members = [
                    row
                    for row in roster
                    if (_text(row.get(field)) or "未标注") == region_value
                    and _text(row.get("实验臂")) == arm_value
                ]
                if not members:
                    continue
                numerator = sum(1 for row in members if _as_bool(row.get("转化")))
                cells.append({
                    "地区": region_value,
                    "实验臂": arm_value,
                    "分母": len(members),
                    "分子": numerator,
                    "转化率": _rate(numerator, len(members)),
                })
        return cells

    # ------------------------------------------------------------------ 曝光核对
    def reconcile(self, entry_id: int, participant_id: str) -> dict[str, Any]:
        entry = self.experiment(entry_id)
        code = self._code(entry)
        participant_id = _text(participant_id)
        roster_row = next(
            (row for row in self._roster(code) if _text(row.get("参与者编号")) == participant_id),
            None,
        )
        observations = [
            row
            for row in self._observations(code)
            if _text(row.get("参与者编号")) == participant_id
        ]
        if roster_row is None:
            pending = [self._pending_item(row) for row in observations]
            raise SampleError(
                f"参与者 {participant_id} 没有进入实验样本分配表，"
                f"关联观测 {len(pending)} 条仍待归属",
                status_code=404,
            )

        exposures = [row for row in observations if _is_exposure(row)]
        armed_rows = [row for row in observations if _arm(row)]
        source_arms = _ordered_unique([_arm(row) for row in armed_rows])
        exposure_arms = _ordered_unique([_arm(row) for row in exposures])
        roster_arm = _text(roster_row.get("实验臂"))
        first_exposure_at = _text(roster_row.get("首次曝光时间"))
        first_exposure_time = _parse_time(first_exposure_at)
        other_arm_records = [
            {
                "观测编号": _text(row.get("观测编号")),
                "观测时间": _text(row.get("观测时间")),
                "分组字段": _arm(row),
                "事件类型": _text(row.get("事件类型")),
                "地区": _region(row),
            }
            for row in armed_rows
            if _arm(row) != roster_arm
        ]
        # 比名单首次曝光更早、后来才补录进来的曝光记录：已发生的曝光不重新分组，
        # 但如果这次曝光早于名单登记时间，说明原分组可能认错了，必须单独提示。
        earlier_exposure_records = [
            {
                "观测编号": _text(row.get("观测编号")),
                "观测时间": _text(row.get("观测时间")),
                "分组字段": _arm(row),
                "地区": _region(row),
            }
            for row in armed_rows
            if first_exposure_time is not None
            and (_parse_time(row.get("观测时间")) or datetime.max) < first_exposure_time
        ]
        start_region = _text(roster_row.get("启动时地区"))
        current_region = _text(roster_row.get("更正后地区"))
        observation_regions = _ordered_unique([_region(row) for row in observations])
        # 曝光时地区取名单首次曝光那条记录的地区，而不是任意一条曝光记录：没有分组
        # 字段的曝光无法说明进入的是哪个实验臂，事后补录的早期曝光也不改变历史。
        entry_exposure = next(
            (
                row
                for row in armed_rows
                if _text(row.get("观测时间")) == first_exposure_at
            ),
            None,
        )
        if entry_exposure is None:
            entry_exposure = next(
                (row for row in armed_rows if _arm(row) == roster_arm), None
            )
        exposure_region = (
            _region(entry_exposure) if entry_exposure else ""
        ) or start_region
        region_conflict = bool(current_region) and current_region != exposure_region

        roster = self._roster(code)
        denominator_contribution: list[dict[str, Any]] = []
        for basis, field in REGION_BASES.items():
            region_used = _text(roster_row.get(field))
            arm_members = [
                row
                for row in roster
                if _text(row.get("实验臂")) == roster_arm and _text(row.get(field)) == region_used
            ]
            denominator_contribution.append({
                "region_basis": basis,
                "地区口径": field,
                "筛选所用地区": region_used,
                "实验臂": roster_arm,
                "所在臂分母": len(arm_members),
                "所在臂分子": sum(
                    1 for row in arm_members if _as_bool(row.get("转化"))
                ),
                "本人是否计入该分母": any(
                    _text(row.get("参与者编号")) == participant_id for row in arm_members
                ),
            })

        findings = [
            f"参与者 {participant_id} 在名单中的实验臂为「{roster_arm}」，"
            f"首次曝光时间 {_text(roster_row.get('首次曝光时间'))}。",
            "历史曝光记录已重新查询；实际分组以首次曝光的分组字段为准，后续记录不重新分组。",
        ]
        if other_arm_records:
            findings.append(
                f"来源记录中另有 {len(other_arm_records)} 条与名单不一致的分组字段"
                f"（{'、'.join(_ordered_unique([item['分组字段'] for item in other_arm_records]))}），"
                f"这些记录仍只计入「{roster_arm}」，不会把同一次观测算进两个实验臂。"
            )
        if earlier_exposure_records:
            findings.append(
                f"另有 {len(earlier_exposure_records)} 条曝光记录的观测时间早于名单首次曝光"
                f"（{first_exposure_at}），属于事后补录；已发生的曝光按名单中的实际分组计入"
                f"「{roster_arm}」，需要人工确认是否应回溯修正名单。"
            )
        if start_region != current_region:
            findings.append(
                f"地区已由「{start_region}」更正为「{current_region}」：复验原分层设计用启动时地区"
                f"「{start_region}」，回答当前地区的响应差异用更正后地区「{current_region}」。"
            )
            findings.append(
                f"按启动时地区筛选时，该参与者出现在「{start_region}／{roster_arm}」的分母里；"
                f"按更正后地区筛选时，出现在「{current_region}／{roster_arm}」的分母里，"
                "两种口径都只计 1 人。"
            )
        else:
            findings.append(
                f"曝光时地区与当前来源地区一致，均为「{start_region}」；"
                "两种地区口径的筛选结果相同。"
            )

        return {
            "experiment": entry,
            "参与者编号": participant_id,
            "roster": roster_row,
            "arm_check": {
                "名单实验臂": roster_arm,
                "历史曝光中的实验臂": exposure_arms,
                "来源记录中的分组字段": source_arms,
                "分组冲突": len(source_arms) > 1 or roster_arm not in source_arms,
                "其他分组字段记录": other_arm_records,
                "早于名单首次曝光的补录曝光": earlier_exposure_records,
            },
            "region_check": {
                "启动时地区": start_region,
                "曝光时记录地区": exposure_region,
                "更正后地区": current_region,
                "观测地区": observation_regions,
                "地区已更正": start_region != current_region,
                "与曝光时记录冲突": region_conflict,
            },
            "exposure_records": [
                {
                    "观测编号": _text(row.get("观测编号")),
                    "观测时间": _text(row.get("观测时间")),
                    "分组字段": _arm(row),
                    "地区": _region(row),
                    "事件类型": _text(row.get("事件类型")),
                    "是否计入分组": _arm(row) == roster_arm,
                }
                for row in exposures
            ],
            "observation_records": [
                {
                    "观测编号": _text(row.get("观测编号")),
                    "观测时间": _text(row.get("观测时间")),
                    "分组字段": _arm(row),
                    "地区": _region(row),
                    "转化": _as_bool(row.get("转化")),
                    "事件类型": _text(row.get("事件类型")),
                }
                for row in observations
            ],
            "denominator_contribution": denominator_contribution,
            "findings": findings,
        }


service = SampleService()
