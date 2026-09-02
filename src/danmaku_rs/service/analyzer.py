from __future__ import annotations

import time
from typing import Dict, List, Optional

from danmaku_rs.types import FATAL_API_CODES, Alert, AlertLevel, LiveSnapshot

_LEVEL_RANK = {AlertLevel.INFO: 1, AlertLevel.WARNING: 2, AlertLevel.CRITICAL: 3}


def analyze(snap: LiveSnapshot, previous: Optional[LiveSnapshot] = None) -> List[Alert]:
    now = time.time()
    alerts: List[Alert] = []

    if snap.login_ok is False:
        alerts.append(
            Alert(
                AlertLevel.CRITICAL,
                "login",
                f"登录失效：{snap.login_msg or 'Cookie 无效或已过期'}",
                "到「账号」页重新检测并保存 Cookie",
                now,
            )
        )
    elif previous and previous.login_ok is False and snap.login_ok:
        alerts.append(Alert(AlertLevel.INFO, "login_ok", "登录已恢复", "可继续补档", now))

    if snap.poll_error:
        alerts.append(
            Alert(AlertLevel.WARNING, "poll", f"巡检拉取失败：{snap.poll_error}", "检查网络或代理后重试", now)
        )

    if snap.intercept_412:
        alerts.append(
            Alert(
                AlertLevel.CRITICAL,
                "http412",
                f"请求被拦截 HTTP 412 ×{snap.intercept_412}",
                "暂停发送，更换网络/降低频率后再试",
                now,
            )
        )

    if snap.last_code in FATAL_API_CODES:
        alerts.append(
            Alert(
                AlertLevel.CRITICAL,
                f"fatal_{snap.last_code}",
                f"致命接口码 {snap.last_code}",
                "停止当前账号，检查登录态、权限或稿件状态",
                now,
            )
        )

    if snap.rate_limit_hits:
        alerts.append(
            Alert(
                AlertLevel.WARNING,
                "rate_36703",
                f"触发频率限制 36703 ×{snap.rate_limit_hits}",
                "加长间隔，或减少同时发送的账号数",
                now,
            )
        )

    attempts = snap.send_success + snap.send_failed
    if attempts >= 5 and snap.send_failed / attempts >= 0.3:
        alerts.append(
            Alert(
                AlertLevel.WARNING,
                "fail_rate",
                f"失败率 {snap.send_failed}/{attempts} = {snap.send_failed / attempts:.0%}",
                "先模拟核对内容，或把任务分给更多账号",
                now,
            )
        )

    if snap.consecutive_fail >= 3:
        alerts.append(
            Alert(
                AlertLevel.WARNING,
                "fail_streak",
                f"连续失败 {snap.consecutive_fail} 次",
                "检查该账号是否被限流，必要时停用它",
                now,
            )
        )

    if snap.local_count and snap.coverage < 0.35 and not snap.simulate:
        alerts.append(
            Alert(
                AlertLevel.WARNING,
                "coverage_low",
                f"线上覆盖率仅 {snap.coverage:.1%}（本地 {snap.local_count} / 线上 {snap.online_count}）",
                "继续补档或核销历史中的丢失条目",
                now,
            )
        )

    if previous and snap.local_count and snap.coverage + 0.08 < previous.coverage:
        alerts.append(
            Alert(
                AlertLevel.WARNING,
                "coverage_drop",
                f"覆盖率从 {previous.coverage:.1%} 降到 {snap.coverage:.1%}",
                "可能被清弹幕，建议立刻核销并复查稿件",
                now,
            )
        )

    if snap.lost and snap.lost >= max(3, snap.verified):
        alerts.append(
            Alert(
                AlertLevel.WARNING,
                "lost",
                f"已核销丢失 {snap.lost} 条（存活 {snap.verified}）",
                "确认稿件是否允许弹幕，或重新发送丢失条目",
                now,
            )
        )

    if previous and previous.sending and not snap.sending and snap.send_failed == 0 and snap.send_success:
        alerts.append(Alert(AlertLevel.INFO, "run_ok", f"本轮发送结束，成功 {snap.send_success}", "", now))

    return alerts


def merge_alerts(existing: List[Alert], incoming: List[Alert], cooldown: float = 60.0) -> List[Alert]:
    latest: Dict[str, Alert] = {alert.code: alert for alert in existing}
    now = time.time()
    for alert in incoming:
        old = latest.get(alert.code)
        if old and now - old.ts < cooldown and _LEVEL_RANK[alert.level] <= _LEVEL_RANK[old.level]:
            continue
        latest[alert.code] = alert
    merged = sorted(latest.values(), key=lambda item: (-_LEVEL_RANK[item.level], -item.ts))
    return merged[:80]


def worst_level(alerts: List[Alert]) -> Optional[AlertLevel]:
    if not alerts:
        return None
    return max(alerts, key=lambda item: _LEVEL_RANK[item.level]).level
