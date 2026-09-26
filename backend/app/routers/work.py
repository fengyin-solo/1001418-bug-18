"""养护施工接口：维护施工任务，覆盖确认开工、提交验收、确认完工等动作。"""
from __future__ import annotations

from typing import Any

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.work import STATUS_ORDER, WorkRuleError, WorkService

router = APIRouter(prefix="/api/work", tags=["养护施工"])

service = WorkService()

LIST_FIELDS = ["施工编号", "关联计划", "承接单位", "开工日期", "完工日期", "完成工程量", "监理人员", "施工状态"]
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按施工编号检索"),
    status: str | None = Query(default=None, description="待开工、施工中、待验收、已完工"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按施工编号与状态过滤养护施工列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 固定路径必须排在 /{entry_id} 前面，否则会被当成任务 id 解析（导出曾因此 422）
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出养护施工清单：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "work", "total": total, "items": items}


@router.get("/stats")
def stats_entries() -> dict[str, Any]:
    """列表页卡片口径：各状态件数与本月完工数，跟明细同一份数据。"""
    items, _ = service.list_entries(page=1, size=10000)
    counts = {status: 0 for status in STATUSES}
    month_finished = 0
    for row in items:
        status = str(row.get("status") or "")
        if status in counts:
            counts[status] += 1
        if status == "已完工" and str(row.get("完工日期") or "")[:7] == date.today().strftime("%Y-%m"):
            month_finished += 1
    return {"counts": counts, "本月完工数": month_finished}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条施工任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"施工任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条施工任务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="施工任务已登记", entry=entry)


@router.patch("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """补录施工资料（完工日期、完成工程量、监理人员等），用于完工前补齐字段。"""
    entry, message = service.update_entry(entry_id, payload.values)
    if entry is None:
        raise HTTPException(status_code=404, detail=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条施工任务执行确认开工、提交验收、确认完工。

    状态机、幂等与完工字段校验都在服务层；不通过时用非 2xx 状态码拒绝，
    响应体 detail 讲清是当前哪一头（状态）不允许。
    """
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.run_action(entry_id, action, payload.values)
    except WorkRuleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return ActionResult(ok=True, message=message, entry=entry)
