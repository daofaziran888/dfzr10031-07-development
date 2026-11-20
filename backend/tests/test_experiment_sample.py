"""实验样本分配的服务层测试：归并、分组稳定、地区口径、聚合与核对。"""
from __future__ import annotations

import pytest

from app.services.experiment_sample import SampleError, service
from app.store import store

ENTRY_ID = 3  # EXPE-0003，运行中，带示例观测


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    store.reset()


def _participant(participant_id: str) -> dict:
    roster = service.roster(ENTRY_ID)
    return next(row for row in roster["participants"] if row["参与者编号"] == participant_id)


def _add(participant: str, observed_at: str, arm: str = "", region: str = "", converted: bool = False, event: str = ""):
    values = {
        "参与者编号": participant,
        "观测时间": observed_at,
        "分组字段": arm,
        "地区": region,
        "转化": converted,
    }
    if event:
        values["事件类型"] = event
    return service.add_observation(ENTRY_ID, values)


def test_sync_merges_multiple_observations_into_one_roster_row() -> None:
    summary = service.sync_roster(ENTRY_ID)
    roster = service.roster(ENTRY_ID)

    participants = [row["参与者编号"] for row in roster["participants"]]
    assert len(participants) == len(set(participants))
    assert summary["participants"] == 9
    assert summary["observations"] == 22

    participant = _participant("PART-0001")
    assert participant["观测条数"] == 3
    assert participant["曝光条数"] == 1
    assert participant["转化"] is True


def test_participant_only_enters_first_exposure_arm() -> None:
    service.sync_roster(ENTRY_ID)

    # PART-0008 有两条曝光、都写实验组；PART-0007 的第二条曝光写实验组，但首次曝光是对照组。
    assert _participant("PART-0008")["实验臂"] == "实验组"
    participant = _participant("PART-0007")
    assert participant["实验臂"] == "对照组"
    assert participant["分组冲突"] is True

    aggregate = service.aggregate(ENTRY_ID)
    arm_members = {
        cell["实验臂"]: cell["分母"] for cell in aggregate["arm_totals"]
    }
    assert arm_members == {"对照组": 4, "实验组": 5}
    assert sum(arm_members.values()) == aggregate["totals"]["分母"] == 9


def test_late_observation_cannot_move_exposed_participant() -> None:
    service.sync_roster(ENTRY_ID)
    _add("PART-0003", "2026-09-20T10:00", arm="对照组", region="华北", event="曝光")

    participant = _participant("PART-0003")
    assert participant["实验臂"] == "实验组"
    assert participant["启动时地区"] == "华南"
    assert participant["更正后地区"] == "华北"

    aggregate = service.aggregate(ENTRY_ID)
    by_arm = {cell["实验臂"]: cell["分母"] for cell in aggregate["arm_totals"]}
    assert by_arm == {"对照组": 4, "实验组": 5}
    assert aggregate["totals"]["分母"] == 9


def test_region_correction_keeps_start_stratum_and_answers_current_region() -> None:
    service.sync_roster(ENTRY_ID)
    participant = _participant("PART-0007")
    assert participant["启动时地区"] == "华东"
    assert participant["更正后地区"] == "华南"

    start = service.aggregate(ENTRY_ID, region="华东", region_basis="start")
    current = service.aggregate(ENTRY_ID, region="华东", region_basis="current")
    assert start["totals"]["分母"] == 4
    assert current["totals"]["分母"] == 3

    start_south = service.aggregate(ENTRY_ID, region="华南", region_basis="start")
    current_south = service.aggregate(ENTRY_ID, region="华南", region_basis="current")
    assert start_south["totals"]["分母"] == 2
    assert current_south["totals"]["分母"] == 3

    report = service.report(ENTRY_ID)
    corrected = report["corrected_participants"]
    assert [item["参与者编号"] for item in corrected] == ["PART-0007"]
    assert corrected[0]["实验臂"] == "对照组"


def test_unattributed_observations_are_listed_separately_and_filtered_by_scope() -> None:
    service.sync_roster(ENTRY_ID)
    aggregate = service.aggregate(ENTRY_ID)
    pending_ids = {item["观测编号"] for item in aggregate["pending_observations"]}
    assert pending_ids == {"OBSV-0018", "OBSV-0021", "OBSV-0022"}
    assert aggregate["totals"]["分母"] == 9
    assert aggregate["totals"]["待归属观测"] == 3

    # 未加入名单的转化观测不进入任何实验臂的分子。
    assert aggregate["totals"]["分子"] == 6
    arm_numerators = {cell["实验臂"]: cell["分子"] for cell in aggregate["arm_totals"]}
    assert sum(arm_numerators.values()) == 6

    region_scope = service.aggregate(ENTRY_ID, region="华北")
    assert region_scope["totals"]["待归属观测"] == 1
    assert [item["观测编号"] for item in region_scope["pending_observations"]] == ["OBSV-0021"]
    assert region_scope["totals"]["分母"] == 3
    assert region_scope["totals"]["分子"] == 2


def test_arm_filter_keeps_pending_observations_in_same_scope() -> None:
    service.sync_roster(ENTRY_ID)
    aggregate = service.aggregate(ENTRY_ID, arm="对照组")
    assert aggregate["totals"]["分母"] == 4
    assert aggregate["totals"]["分子"] == 1
    assert {cell["实验臂"] for cell in aggregate["cells"]} == {"对照组"}
    assert aggregate["totals"]["待归属观测"] == 3

    scoped = service.aggregate(ENTRY_ID, region="华南", arm="实验组")
    assert scoped["totals"]["分母"] == 1
    assert scoped["totals"]["分子"] == 1
    assert [item["观测编号"] for item in scoped["pending_observations"]] == [
        "OBSV-0018",
        "OBSV-0022",
    ]


def test_report_explains_population_and_denominator() -> None:
    service.sync_roster(ENTRY_ID)
    report = service.report(ENTRY_ID)
    assert "参与者" in report["population"]["definition"]
    assert report["population"]["included_participants"] == 9
    # 两个参与者编号（PART-0009、PART-0011）没有有效曝光；另有 1 条缺少编号的观测。
    assert report["population"]["excluded_participants"] == 2
    assert report["population"]["excluded_observations"] == 3
    assert report["denominator"]["total"] == 9
    assert report["numerator"]["total"] == 6
    assert "分母" in report["denominator"]["definition"]
    assert report["pending"]["observations"]
    assert report["strata"]["start"]["cells"]
    assert report["strata"]["current"]["cells"]


def test_report_counts_follow_query_scope() -> None:
    service.sync_roster(ENTRY_ID)
    full = service.report(ENTRY_ID)
    scoped = service.report(ENTRY_ID, region="华北")
    assert full["population"]["included_participants"] == 9
    assert scoped["population"]["included_participants"] == 3
    assert scoped["population"]["roster_participants"] == 9
    assert scoped["population"]["counts_use_query_scope"] is True
    assert scoped["population"]["excluded_observations"] == 1
    assert scoped["denominator"]["total"] == 3


def test_reconcile_corrected_participant_counts_once_per_arm() -> None:
    service.sync_roster(ENTRY_ID)
    result = service.reconcile(ENTRY_ID, "PART-0007")

    assert result["roster"]["实验臂"] == "对照组"
    assert result["arm_check"]["分组冲突"] is True
    assert [rec["分组字段"] for rec in result["exposure_records"]] == ["对照组", "实验组"]
    assert [rec["是否计入分组"] for rec in result["exposure_records"]] == [True, False]
    assert result["region_check"] == {
        "启动时地区": "华东",
        "曝光时记录地区": "华东",
        "更正后地区": "华南",
        "观测地区": ["华东", "华南"],
        "地区已更正": True,
        "与曝光时记录冲突": True,
    }

    contributions = {
        item["region_basis"]: item for item in result["denominator_contribution"]
    }
    assert contributions["start"]["筛选所用地区"] == "华东"
    assert contributions["start"]["所在臂分母"] == 2
    assert contributions["current"]["筛选所用地区"] == "华南"
    assert contributions["current"]["所在臂分母"] == 2
    assert all(item["本人是否计入该分母"] for item in contributions.values())

    # 该参与者只出现在一个实验臂的分母里，不会因为两条分组字段不同的曝光被算两次。
    assert result["arm_check"]["名单实验臂"] == "对照组"
    assert result["roster"]["实验臂"] not in {"实验组"}


def test_participant_without_exposure_stays_pending() -> None:
    service.sync_roster(ENTRY_ID)
    with pytest.raises(SampleError) as error:
        service.reconcile(ENTRY_ID, "PART-0011")
    assert "待归属" in error.value.message

    roster = service.roster(ENTRY_ID)
    assert "PART-0011" not in {row["参与者编号"] for row in roster["participants"]}


def test_sync_requires_designed_experiment() -> None:
    with pytest.raises(SampleError) as error:
        service.sync_roster(1)  # EXPE-0001 仍是草稿
    assert "草稿" in error.value.message


def test_sync_is_idempotent() -> None:
    first = service.sync_roster(ENTRY_ID)
    second = service.sync_roster(ENTRY_ID)
    assert first["participants"] == second["participants"] == 9
    assert second["created"] == 0
    assert second["updated"] == 9
