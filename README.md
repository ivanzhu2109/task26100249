# DeskPilot 循环日程冲突检查库

纯 Python（仅标准库）、进程内存内运行的日程冲突检查库。上层在保存日程前调用，
用于判断拟新增日程与哪些已有日程冲突，并返回第一次撞期的证据。

## 功能

- 一次载入一组已有日程，反复检查拟新增日程；检查不修改已有数据，也不检查已有日程之间的冲突。
- 重复类型：不重复 / 每日 / 每周 / 每月。每月保持首次的日号与时分秒，某月没有该日号则跳过整月。
- 公历 + UTC，精确到秒；单次持续时间 > 0 且 <= 72 小时，后续发生保持首次持续时间。
- 时间区间为左闭右开 [start, end)：一个刚结束、另一个恰好开始不算冲突。
- 循环日程无结束日期；对每条冲突的已有日程只报告一次，给出最早重叠时刻及双方发生区间作为证据；
  无冲突时给出确定结论（基于每日/每周的最小公倍周期或 400 年公历闰年周期判定）。

## 使用

    from datetime import datetime, timezone
    from deskpilot import ConflictChecker, Recurrence, Schedule

    utc = timezone.utc
    existing = [
        Schedule("m", datetime(2021, 1, 31, 9, tzinfo=utc),
                 datetime(2021, 1, 31, 10, tzinfo=utc), Recurrence.MONTHLY),
    ]
    checker = ConflictChecker(existing)

    candidate = Schedule("w", datetime(2021, 2, 4, 9, 30, tzinfo=utc),
                         datetime(2021, 2, 4, 10, 30, tzinfo=utc), Recurrence.WEEKLY)
    result = checker.check(candidate)
    if result.has_conflict:
        for c in result.conflicts:
            print(c.schedule_id, c.overlap_start,
                  c.existing_occurrence, c.candidate_occurrence)
    # 输出: m 2022-03-31 09:30:00+00:00 ...

## 运行测试

    python3 -m pytest tests/ -q

## 项目结构

- deskpilot/core.py — 数据类型、发生序列生成、最早重叠判定、ConflictChecker
- deskpilot/__init__.py — 公开 API 导出
- tests/test_conflicts.py — 自动化测试（含与逐次枚举发生记录的交叉核对）
