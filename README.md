# DeskPilot 循环日程冲突检查库

纯 Python、零依赖的进程内库，由上层在保存日程前调用，检查拟新增日程与已有日程的冲突。日程数据仅保存在进程内存中，不使用任何外部服务、数据库或端口。

## 规则

- 每条日程：唯一标识、首次开始/结束时刻（公历 UTC，精确到秒）、重复类型。
- 单次持续时间 > 0 且 ≤ 72 小时，后续每次发生保持首次的持续时间（可跨日、跨月）。
- 重复类型：`NONE`（仅一次）、`DAILY`（每隔一天）、`WEEKLY`（每隔七天）、`MONTHLY`（保持首次的日号与时分秒；某月没有该日号就跳过整月，不改为月末，也不影响后续月份）。
- 循环无结束日期，首次开始之前没有发生记录。
- 区间为半开 `[start, end)`：一个刚结束、另一个恰好开始不算冲突。
- 同一日程的自身重叠不报告，也不影响与其他日程的判断。

## 使用

```python
from datetime import datetime, timezone
from deskpilot import ConflictChecker, Recurrence, Schedule

U = timezone.utc
existing = Schedule(
    id="monthly-report",
    start=datetime(2021, 1, 31, 9, 0, tzinfo=U),
    end=datetime(2021, 1, 31, 10, 0, tzinfo=U),
    recurrence=Recurrence.MONTHLY,
)
checker = ConflictChecker([existing])   # 一次载入，反复检查

candidate = Schedule(
    id="weekly-sync",
    start=datetime(2021, 2, 4, 9, 30, tzinfo=U),
    end=datetime(2021, 2, 4, 10, 30, tzinfo=U),
    recurrence=Recurrence.WEEKLY,
)
conflicts = checker.check(candidate)
# [Conflict(schedule_id='monthly-report',
#           overlap_start=datetime(2022, 3, 31, 9, 30, tzinfo=utc), ...)]
```

- `check()` 对每条冲突的已有日程只返回一个 `Conflict`，包含最早重叠时刻 `overlap_start` 及双方对应的发生区间作为证据；空列表表示确定无冲突（任何未来时刻都不会重叠）。
- 检查不修改已有数据，也不检查已有日程彼此之间的冲突。
- `deskpilot.occurrences_between(schedule, lo, hi)` 可列出与窗口 `[lo, hi)` 相交的全部发生记录，便于核对。

## 运行测试

```bash
python3 -m pytest tests/ -q
```

## 实现要点

`deskpilot/conflicts.py` 用双指针合并两条按开始时刻升序的发生序列，找到的第一对重叠即为最早撞期证据。终止判定利用周期性：日/周组合的共同模式以周期 `lcm(周期)` 重复，凡涉及每月的组合以公历 400 年（146097 天，整周数）为周期重复；扫描超过 `max(首次开始) + 周期 + 双方时长` 仍未重叠即可确定永不冲突。
