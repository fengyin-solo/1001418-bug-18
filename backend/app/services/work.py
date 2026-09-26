"""养护施工业务规则：状态流转、字段校验与筛选口径都收在这里。

流转链路只有一条：待开工 → 施工中 → 待验收 → 已完工。
动作与状态严格对齐：只有当前状态对应的动作能执行，跳级、倒退、重复点击都会被拦下。
"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "work"
REQUIRED_FIELDS = ["施工编号", "关联计划", "承接单位"]
# 完工前必须补齐的字段，缺一项就不允许确认完工
COMPLETION_FIELDS = ["完工日期", "完成工程量", "监理人员"]
STATUS_ORDER = ["待开工", "施工中", "待验收", "已完工"]
ACTION_RULES = {"确认开工": "施工中", "提交验收": "待验收", "确认完工": "已完工"}
# 每个状态允许执行的动作；不在表里的动作一律拒绝
ALLOWED_ACTIONS: dict[str, list[str]] = {
    "待开工": ["确认开工"],
    "施工中": ["提交验收"],
    "待验收": ["确认完工"],
    "已完工": [],
}
STATUS_FIELD = "施工状态"
NEGATIVE_ACTIONS = []


class WorkRuleError(Exception):
    """业务规则不通过：路由层转成带状态码的 HTTP 响应，把原因讲清楚。"""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class WorkService:
    def __init__(self) -> None:
        # 动作要"只生效一次"：用锁挡住同一任务并发的重复提交
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, entry_id: int) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(entry_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[entry_id] = lock
            return lock

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("施工编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        # 必填项之外，开工/完工等补充字段也一并落库，避免后续动作查不到
        for field in REQUIRED_FIELDS + COMPLETION_FIELDS:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry[STATUS_FIELD] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def update_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """补录开工/完工资料，供完工前补齐字段；只接受已有的施工资料字段。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"施工任务 {entry_id} 不存在或已归档"
        editable = [field for field in REQUIRED_FIELDS if field not in ("施工编号",)]
        editable += COMPLETION_FIELDS
        for field in editable:
            value = values.get(field)
            if value is not None:
                entry[field] = value
        return entry, "施工任务资料已更新"

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise WorkRuleError(f"施工任务 {entry_id} 不存在或已归档", status_code=404)
        if action not in ACTION_RULES:
            raise WorkRuleError(f"动作「{action}」不属于养护施工可执行范围", status_code=400)

        with self._lock_for(entry_id):
            current = str(entry.get("status") or "")
            allowed = ALLOWED_ACTIONS.get(current, [])
            if not allowed:
                raise WorkRuleError(
                    f"施工任务当前为「{current}」，流程已结束，不能再执行「{action}」"
                )
            if action not in allowed:
                raise WorkRuleError(
                    f"「{current}」状态不允许执行「{action}」，"
                    f"当前只允许：{'、'.join(allowed)}"
                )

            # 确认完工时把补齐的资料先收下，再按"字段没填全不允许完工"兜底校验
            if action == "确认完工" and values:
                for field in COMPLETION_FIELDS:
                    value = values.get(field)
                    if value is not None:
                        entry[field] = value
            if action == "确认完工":
                missing = [
                    field for field in COMPLETION_FIELDS
                    if not str(entry.get(field) or "").strip()
                ]
                if missing:
                    raise WorkRuleError(
                        f"字段未填全，不能确认完工，请先补齐：{'、'.join(missing)}",
                        status_code=422,
                    )

            target = ACTION_RULES[action]
            entry["status"] = target
            entry[STATUS_FIELD] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = action in NEGATIVE_ACTIONS
            return entry, f"施工任务已{action}，当前状态：{target}"
