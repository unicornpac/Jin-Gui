"""
导入质量闸门 —— 在写入 classic_texts 前执行硬性质量检查。

只有通过所有预设规则的批次才能发布到正式条文库。
"""
import json
from typing import List, Dict, Optional
from collections import Counter


def validate_import_batch(
    articles: List[dict],
    expected_book: str = "《伤寒论》",
) -> dict:
    """
    对一批解析出的条文进行质检，生成质检报告。

    Args:
        articles: 解析出的条文列表，每项包含 article_number, content, raw_content, chapter 等
        expected_book: 预期书藉（用于预期条号范围）

    Returns:
        {
            "passed": bool,           # 是否通过所有硬性检查
            "expected_count": int,    # 预期唯一条号数
            "actual_unique": int,     # 实际唯一条号数
            "total_parsed": int,      # 解析出的总条数
            "missing_numbers": list,  # 缺失条号
            "duplicates": dict,       # {条号: 出现次数}
            "duplicate_details": list,# 重复详情的待裁决列表
            "empty_content": list,    # 空正文的条号
            "overlong_content": list, # 超长正文的条号
            "unassigned_chapter": list, # 无章节归属的条号
            "issues": list,           # 人类可读的问题描述
            "warnings": list,         # 警告（不阻止发布）
        }
    """
    report = {
        "passed": True,
        "expected_count": 0,
        "actual_unique": 0,
        "total_parsed": len(articles),
        "missing_numbers": [],
        "duplicates": {},
        "duplicate_details": [],
        "empty_content": [],
        "overlong_content": [],
        "unassigned_chapter": [],
        "issues": [],
        "warnings": [],
    }

    # ── 条号统计 ──
    nums = []
    for art in articles:
        n = art.get("article_number")
        if n is not None and isinstance(n, int) and 1 <= n <= 500:
            nums.append(n)

    if not nums:
        report["passed"] = False
        report["issues"].append("未识别到任何有效条号")
        return report

    num_counts = Counter(nums)
    unique_nums = sorted(num_counts.keys())

    report["actual_unique"] = len(unique_nums)
    report["total_parsed"] = len(articles)

    # ── 预期条号范围 ──
    if expected_book == "《伤寒论》":
        expected_range = range(1, 399)  # 1-398
        report["expected_count"] = 398
    elif expected_book == "《金匮要略》":
        expected_range = range(1, 26)  # 25篇（条号格式不同）
        report["expected_count"] = None  # 金匮条号不是简单整数
    else:
        # 未知书藉，不设预期
        report["expected_count"] = None
        return report

    # ── 缺失检查 ──
    expected_set = set(expected_range)
    actual_set = set(unique_nums)
    missing = sorted(expected_set - actual_set)
    report["missing_numbers"] = missing
    if missing:
        report["issues"].append(
            f"缺失条号 {len(missing)} 个: {missing[:10]}{'...' if len(missing) > 10 else ''}"
        )
        # 缺失不阻止发布（可能是底本不全），仅警告
        report["warnings"].append(f"缺失 {len(missing)} 个条号，请确认底本完整性")

    # ── 重复检查（硬性闸门）──
    duplicates = {n: c for n, c in num_counts.items() if c > 1}
    report["duplicates"] = duplicates
    if duplicates:
        report["passed"] = False
        for n, c in duplicates.items():
            dup_items = [a for a in articles if a.get("article_number") == n]
            report["duplicate_details"].append({
                "article_number": n,
                "count": c,
                "needs_review": True,
                "contents": [a.get("content", "")[:100] for a in dup_items],
                "raw_contents": [a.get("raw_content", "")[:100] for a in dup_items],
            })
            report["issues"].append(
                f"条号 {n} 重复出现 {c} 次，需人工裁决（确认是底本异文、排版错误，还是应使用子编号）"
            )

    # ── 空正文检查 ──
    empty = [a.get("article_number") for a in articles
             if not a.get("content") or len(a.get("content", "").strip()) < 10]
    report["empty_content"] = empty
    if empty:
        report["passed"] = False
        report["issues"].append(f"空正文条号: {empty}")

    # ── 超长正文 ──
    overlong = [a.get("article_number") for a in articles
                if len(a.get("content", "")) > 3000]
    report["overlong_content"] = overlong
    if overlong:
        report["warnings"].append(f"超长正文条号: {overlong}")

    # ── 无章节归属 ──
    unassigned = [a.get("article_number") for a in articles
                  if not a.get("chapter")]
    report["unassigned_chapter"] = unassigned
    if unassigned:
        report["warnings"].append(
            f"无章节归属的条号 {len(unassigned)} 个: {unassigned[:10]}{'...' if len(unassigned) > 10 else ''}"
        )

    return report


def format_report_text(report: dict) -> str:
    """将质检报告格式化为可读文本"""
    lines = [
        f"预期唯一条号：{report.get('expected_count', '?')}",
        f"实际识别的唯一条号：{report['actual_unique']}",
        f"识别到的正文段数：{report['total_parsed']}",
        f"缺失条号：{report['missing_numbers'] or '[]'}",
        f"重复条号：{list(report['duplicates'].keys()) or '[]'}",
        f"空正文：{report['empty_content'] or '[]'}",
        f"超长正文：{report['overlong_content'] or '[]'}",
        f"无章节归属：{report['unassigned_chapter'] or '[]'}",
    ]
    if report.get("issues"):
        lines.append(f"\n问题：")
        for issue in report["issues"]:
            lines.append(f"  - {issue}")
    if report.get("warnings"):
        lines.append(f"\n警告：")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    return "\n".join(lines)
