"""训练链路验证脚本 —— 两种模式。

quick（默认）
    起一个会话，直接往库里补几条学生发言，然后走 /evaluate，
    检查 scoring 是否正确下发。不调用对话模型，几秒出结果。
    用途：改完评分逻辑后，快速确认整条链路没被弄坏。

replay
    按内置发言逐轮走真实训练：每轮打印四阶段进度与会话状态，结束后评价。
    用于验证「学生没开方时不该提前结束」这类流程问题。
    每轮都会调模型，较慢（一分钟上下）。

前置条件
    - 本地服务已启动（默认 http://127.0.0.1:8000）
    - 病案已配置 scoring_points，否则 scoring 会是 null、脚本会说明这一点
    - 管理员密码：读 backend/.env 的 ADMIN_PASSWORD，用于清理测试会话；
      读不到就跳过清理，并把会话 id 告诉你

用法
    python tools/verify_training.py --case 12 --level 高级
    python tools/verify_training.py --mode replay --case 12
    python tools/verify_training.py --keep          # 保留测试会话

退出码
    0 正常 / 1 链路异常 / 2 replay 模式下提前结束（视为缺陷）
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "backend" / "data" / "tcm.db"

QUICK_LINES = [
    "您这个反复感冒多久了？一般什么季节容易犯？",
    "平时口苦吗？心情怎么样，容易心烦吗？胃口如何？",
    "结合脉弦、口苦、心烦，我认为是少阳枢机不利，病机在枢机不利、卫气不行，"
    "要与表虚不固鉴别。治当和解少阳、调和营卫，方用柴胡桂枝汤。",
]

REPLAY_LINES = [
    "睡觉吃饭怎么样？大小便怎么样？",
    "那就是感冒时常发作，我看看你的脉",
    "再看看你的舌头",
    "那你这是有肝胆的气滞啊",
    "主要问题还是在少阳，营卫不和，正气虚",
    "是，疏风解表的话不能力达体内，应当调和营卫，疏肝解郁",
]

STAGES = ("辨病", "平脉", "析证", "定治")


def admin_headers() -> dict:
    """从 backend/.env 读管理员密码，拼成 Basic Auth 头；没有就返回空。"""
    import base64

    env_path = ROOT / "backend" / ".env"
    password = ""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("ADMIN_PASSWORD="):
                password = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not password:
        return {}
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def start_session(client: httpx.Client, case_id: int, level: str, student: str) -> tuple:
    resp = client.post("/api/agent/session/start", json={
        "difficulty_level": level, "student_id": student, "case_id": case_id,
    })
    resp.raise_for_status()
    data = resp.json()
    print(f"会话 #{data['session_id']}  {data['case_title']}")
    return data["session_id"], data["session_token"]


def inject_student_lines(db_path: Path, session_id: int, lines: list) -> None:
    """直接写库补学生发言，省掉几轮真实对话调用。"""
    conn = sqlite3.connect(str(db_path))
    for line in lines:
        conn.execute(
            "insert into session_messages (session_id, role, content, message_type) "
            "values (?, 'student', ?, null)",
            (session_id, line),
        )
    conn.commit()
    conn.close()
    print(f"已补入 {len(lines)} 条学生发言（直接写库，不调模型）")


def run_replay(client: httpx.Client, session_id: int, token: str, lines: list) -> bool:
    """逐轮真实对话。返回 False 表示中途被判定结束。"""
    headers = {"X-Session-Token": token}
    for index, line in enumerate(lines, start=1):
        resp = client.post(f"/api/agent/session/{session_id}/message",
                           json={"content": line}, headers=headers, timeout=300.0)
        if resp.status_code != 200:
            print(f"[{index}] HTTP {resp.status_code}: {resp.text[:200]}")
            return False
        payload = resp.json()
        progress = payload.get("progress") or {}
        flags = " ".join(f"{s}{'✓' if progress.get(s) else '·'}" for s in STAGES)
        guide = progress.get("guidance") or {}
        print(f"[{index}] {flags}  status={payload.get('session_status')}  "
              f"提示={guide.get('stage')}")
        print(f"     我：{line}")
        print(f"     患者：{(payload.get('agent_message') or '')[:48]}")
        if payload.get("session_status") == "completed":
            print(f"\n>>> 第 {index} 轮被判定结束")
            return False
    print("\n>>> 全部发言走完后仍是 active")
    return True


def evaluate(client: httpx.Client, session_id: int, token: str) -> dict:
    resp = client.post(f"/api/agent/session/{session_id}/evaluate",
                       headers={"X-Session-Token": token}, timeout=300.0)
    if resp.status_code != 200:
        print(f"评价失败 {resp.status_code}: {resp.text[:300]}")
        return {}
    return resp.json()


def report(result: dict) -> int:
    print(f"\nscore = {result.get('score')}")
    scoring = result.get("scoring")
    if not scoring:
        print("scoring = None（该病案没有配置评分要点，走的是旧评分路径）")
        return 0
    print(f"层级 {scoring['level']}  可判定 {scoring['gradable']}  "
          f"得分 {scoring['percent']}%（{scoring['total']}/{scoring['max']}）"
          f"  未计入 {scoring['excluded']} 项")
    for item in scoring["points"]:
        mark = "✓" if item["hit"] else ("✗" if item["hit"] is False else "·")
        evidence = f"  证据：{item['evidence']}" if item.get("evidence") else ""
        print(f"  {mark} [{item['stage']}/{item['min_level']}] "
              f"{item['text'][:36]} ({item['weight']}){evidence}")
    facts = scoring.get("key_facts")
    if facts:
        print(f"关键信息：学生问到 {facts['asked']} / 患者已交代 {facts['revealed']}"
              f" / 仍缺 {facts['missing'] or '无'}")
    review = scoring.get("semantic_review")
    if review:
        print(f"语义复核：送审 {review['checked_points']} 条要点，"
              f"采纳 {review['adopted_points']}、驳回 {review['rejected_points']}；"
              f"信息采纳 {review['adopted_facts']}、驳回 {review['rejected_facts']}")
    return 0


def cleanup(client: httpx.Client, session_id: int, headers: dict) -> None:
    if not headers:
        print(f"\n（没有读到 ADMIN_PASSWORD，会话 #{session_id} 保留，可手动删除）")
        return
    resp = client.delete(f"/api/agent/session/{session_id}", headers=headers, timeout=30.0)
    print(f"\n已清理会话 #{session_id}" if resp.status_code in (200, 204)
          else f"\n清理失败 {resp.status_code}，会话 #{session_id} 保留")


def main() -> int:
    parser = argparse.ArgumentParser(description="训练链路验证")
    parser.add_argument("--mode", choices=("quick", "replay"), default="quick")
    parser.add_argument("--case", type=int, default=12, help="病案 id")
    parser.add_argument("--level", default="高级", help="初级/中级/高级")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 路径（quick 模式用）")
    parser.add_argument("--keep", action="store_true", help="保留测试会话")
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.mode == "quick" and not db_path.exists():
        print(f"数据库不存在：{db_path}")
        return 1

    with httpx.Client(base_url=args.base_url, timeout=120.0) as client:
        try:
            session_id, token = start_session(client, args.case, args.level, "verify_training")
        except Exception as exc:
            print(f"起会话失败：{exc}")
            print("服务是否已启动？可用 tools/restart.ps1 -Check 确认")
            return 1

        ok = True
        if args.mode == "quick":
            inject_student_lines(db_path, session_id, QUICK_LINES)
        else:
            ok = run_replay(client, session_id, token, REPLAY_LINES)

        result = evaluate(client, session_id, token)
        code = report(result) if result else 1

        if not args.keep:
            cleanup(client, session_id, admin_headers())

    if not ok:
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
