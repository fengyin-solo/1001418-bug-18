"""养护施工业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "work"
REQUIRED_FIELDS = ["施工编号", "关联计划", "承接单位"]
STATUS_ORDER = ["待开工", "施工中", "待验收", "已完工"]
# 状态机：每个状态只允许列出的动作，动作执行后流转到目标状态。
ACTION_FLOW: dict[str, dict[str, str]] = {
    "待开工": {"确认开工": "施工中"},
    "施工中": {"提交验收": "待验收"},
    "待验收": {"确认完工": "已完工"},
    "已完工": {},
}
ALL_ACTIONS = [action for rules in ACTION_FLOW.values() for action in rules]
# 确认完工前必须补齐的字段，缺一项就不允许完工。
COMPLETE_REQUIRED_FIELDS = ["开工日期", "完工日期", "完成工程量", "监理人员"]
NEGATIVE_ACTIONS: list[str] = []


class WorkService:
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
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["施工状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"施工任务 {entry_id} 不存在或已归档"
        label = str(entry.get("施工编号") or entry_id)
        if action not in ALL_ACTIONS:
            return None, f"动作「{action}」不属于养护施工可执行范围，可执行动作：{'、'.join(ALL_ACTIONS)}"
        current = str(entry.get("status") or STATUS_ORDER[0])
        allowed = ACTION_FLOW.get(current, {})
        if action not in allowed:
            if allowed:
                return None, (
                    f"施工任务 {label} 当前状态为「{current}」，不允许执行「{action}」；"
                    f"该状态可执行：{'、'.join(allowed)}"
                )
            return None, f"施工任务 {label} 已处于终态「{current}」，不允许再执行任何动作"
        if action == "确认完工":
            missing = [
                field for field in COMPLETE_REQUIRED_FIELDS
                if not str(entry.get(field) or "").strip()
            ]
            if missing:
                return None, f"施工任务 {label} 字段未填全，不允许确认完工，请先补齐：{'、'.join(missing)}"
        target = allowed[action]
        entry["status"] = target
        entry["施工状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"施工任务 {label} 已{action}，状态流转为「{target}」"
