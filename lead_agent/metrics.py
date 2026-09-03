# ===================== A2A 量化测评事件记录器 =====================
# shared/metrics.py —— 权威源（手工同步到 lead_agent/ 与 gameplay_agent/ 各一份）
# 同步命令：
#   cp shared/metrics.py lead_agent/metrics.py
#   cp shared/metrics.py gameplay_agent/metrics.py
#
# 约定：
# - 每端写本端 logs/events.jsonl（logs 目录位于 metrics.py 同级的 agent 目录内）
# - 行格式 JSON，字段：ts / agent / run_id / task_id / event / state / latency_ms / error / model / temp
# - model / temp 从环境变量读取（LLM_MODEL / LLM_TEMPERATURE），由各端 main.py 的 load_dotenv 先行加载
# - 线程安全：threading.Lock（gameplay 的 Flask threaded=True 多线程写同一文件）
# - 归并键：端到端样本用 run_id（lead 每条需求生成）；任务级事件用 task_id（A2A 递交生成）
"""轻量 JSONL 事件记录器（game_planning_studio A2A 量化测评埋点）。"""

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "events.jsonl"
_LOCK = threading.Lock()
_CST = timezone(timedelta(hours=8))

# 事件枚举（与《量化测评方法.md》失败分类对应，新增须同步文档）
EVENT_TYPES = (
    # lead 端
    "request_start",            # 收到老板需求（run 起点）
    "discovery_ok",             # 玩法策划探活成功
    "discovery_fail",           # 玩法策划探活失败
    "lead_plan_ok",             # 主策划方案生成成功
    "lead_plan_fail",           # 主策划 LLM 调用异常
    "a2a_send_start",           # 发起 A2A 递交
    "a2a_completed",            # 递交返回 completed
    "a2a_failed_offline",       # 连不上玩法策划（ConnectionError）
    "a2a_failed_jsonrpc",       # JSON-RPC 返回 error
    "a2a_failed_state",         # 返回 Task 但 state != completed
    "a2a_failed_unknown",       # 其他异常
    "artifact_missing",         # completed 但 artifacts 无 text（异常情况）
    "artifact_saved",           # 玩法方案文本写盘成功
    # gameplay 端
    "task_start",               # 收到任务开始执行
    "task_completed",           # 玩法策划方案生成成功
    "task_failed",              # 玩法策划端异常（置 failed）
)


def now_ms() -> float:
    """当前时间戳（毫秒），作为计时起点"""
    return time.time() * 1000.0


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def log_event(*, agent: str, run_id: str = "", task_id: str = "", event: str,
              state: str = "", error: str = "", latency_ms: float | None = None,
              extra: dict | None = None) -> None:
    """追加写一条事件到本端 logs/events.jsonl（线程安全）。

    参数：
    - agent:   "lead_agent" / "gameplay_agent"
    - run_id:  lead 端每条需求生成；gameplay 端不知则留空（归并用 task_id）
    - task_id: A2A 递交生成的 task_id，gameplay 端用它打点
    - event:   见 EVENT_TYPES
    - state:   completed / failed / working / offline / online 等
    - error:   失败时的错误文本（成功留空）
    - latency_ms: 该事件段耗时（毫秒，now_ms 差值）
    - extra:   额外字段（可选，原样并入记录）
    """
    rec = {
        "ts": datetime.now(_CST).isoformat(timespec="milliseconds"),
        "agent": agent,
        "run_id": run_id or "",
        "task_id": task_id or "",
        "event": event,
        "state": state or "",
        "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
        "error": error or "",
        "model": os.getenv("LLM_MODEL", ""),
        "temp": _num(os.getenv("LLM_TEMPERATURE", "")),
    }
    if extra:
        rec["extra"] = extra
    line = json.dumps(rec, ensure_ascii=False)
    with _LOCK:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_events(path: Path | str) -> list[dict]:
    """读取 events.jsonl 全部事件（供批量 runner 汇总归并使用）"""
    events = []
    p = Path(path)
    if not p.exists():
        return events
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 半行写入等异常情况跳过，不影响统计
    return events
