# ===================== A2A 端到端批量测评 runner =====================
# 量化测评/run_e2e_batch.py —— 运行方式（项目根目录）：
#   uv run --project lead_agent python 量化测评/run_e2e_batch.py [--limit N] [--cases 路径]
#
# 前置：gameplay_agent 服务已启动并在线（play_agent/main.py 监听 8080）。
# 流程：探活 → 逐条执行 lead_main.execute_request → 存档 runs/<run_id>/ → 双端事件归并 → 报告。
# 产物：量化测试报告_<YYYYMMDD>.md（汇总）、runs/<run_id>/（每条样例证据）。
"""game_planning_studio A2A 端到端批量测评 runner（同机双进程版）。"""

import json
import platform
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# 强制 UTF-8 输出（Windows 控制台/重定向文件避免 GBK 乱码）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent          # game_planning_studio
BENCH_DIR = Path(__file__).resolve().parent             # 量化测评/
LEAD_DIR = ROOT / "lead_agent"
GAMEPLAY_DIR = ROOT / "gameplay_agent"
RUNS_DIR = BENCH_DIR / "runs"
LEAD_EVENTS = LEAD_DIR / "logs" / "events.jsonl"
GAMEPLAY_EVENTS = GAMEPLAY_DIR / "logs" / "events.jsonl"

# 使 runner 进程内可直接调用 lead 的 execute_request（同一代码路径，非子进程）
sys.path.insert(0, str(LEAD_DIR))
import main as lead_main  # noqa: E402  (顶层仅建 Agent，不联网、不启动服务)
from metrics import load_events  # noqa: E402

REPORT_NAME = f"量化测试报告_{datetime.now().strftime('%Y%m%d')}.md"
DEFAULT_CASES = BENCH_DIR / "e2e_cases.yaml"


# ===================== 工具 =====================
def probe_gameplay() -> tuple[bool, str]:
    """探活：Agent Card + /health，均通过才视为在线"""
    online, info = lead_main.check_gameplay_agent()
    if not online:
        return False, f"Agent Card 拉取失败: {lead_main.GAMEPLAY_CARD_URI}"
    try:
        health_url = lead_main.GAMEPLAY_URI.rstrip("/") + "/health"
        r = requests.get(health_url, timeout=5)
        if r.status_code != 200 or r.json().get("status") != "running":
            return False, f"/health 异常: HTTP {r.status_code}"
    except Exception as e:
        return False, f"/health 请求失败: {e}"
    return True, f"{info.get('name', 'unknown')} @ {info.get('url', lead_main.GAMEPLAY_URI)}"


def extract_sections(md_text: str) -> list[str]:
    """提取 Markdown 章节名（任意 # 层级，去井号与空白）"""
    names = []
    for line in md_text.splitlines():
        s = line.strip()
        m = re.match(r"^#{1,6}\s+(.+)$", s)
        if m and m.group(1).strip():
            names.append(m.group(1).strip())
    return names


def check_structure(md_text: str, required_groups: list) -> dict:
    """本地结构规则检查（零 LLM 成本）：
    required_groups 每项为 str 或 [关键字...]，章节名包含任一关键字即该组命中。"""
    names = extract_sections(md_text)
    hit, missing = [], []
    for group in required_groups:
        keywords = [group] if isinstance(group, str) else list(group)
        if any(any(k in name for name in names) for k in keywords):
            hit.append(group if isinstance(group, str) else "/".join(group))
        else:
            missing.append(group if isinstance(group, str) else "/".join(group))
    return {"hit": hit, "missing": missing,
            "complete": not missing, "total": len(required_groups)}


def pct(ok: int, total: int) -> str:
    return f"{ok}/{total} = {ok / total * 100:.1f}%" if total else "-"


def stat_ms(items: list[float]) -> str:
    """min/avg/max 秒表示"""
    if not items:
        return "-"
    return f"min {min(items) / 1000:.1f}s / avg {sum(items) / len(items) / 1000:.1f}s / max {max(items) / 1000:.1f}s"


# ===================== 主流程 =====================
def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="A2A 端到端批量测评（同机双进程）")
    ap.add_argument("--cases", default=str(DEFAULT_CASES), help="测试集 YAML 路径")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（默认全部）")
    args = ap.parse_args()

    print("=" * 64)
    print("A2A 端到端批量测评启动")
    print("=" * 64)

    # ---- 1. 读取测试集 ----
    with open(args.cases, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cases = cfg["cases"]
    if args.limit and args.limit < len(cases):
        cases = cases[:args.limit]
    lead_secs = cfg["lead_sections"]
    game_secs = cfg["gameplay_sections"]
    print(f"测试集: {args.cases}（共 {len(cases)} 条）")

    # ---- 2. 探活（不在线则整批中止，不进入统计）----
    print("正在探活玩法策划...", end=" ", flush=True)
    online, detail = probe_gameplay()
    if not online:
        print(f"\n❌ 玩法策划不在线: {detail}\n请先启动 gameplay_agent（uv run python main.py）后重试。")
        return 1
    print(f"✅ {detail}")

    # ---- 3. 逐条执行 ----
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    wall_t0 = time.time()
    for idx, case in enumerate(cases, 1):
        case_id = case["id"]
        run_dir = None
        try:
            # 控制台输出（含 lead/gameplay print）重定向到该样例日志，留档为证据
            print(f"\n[{idx}/{len(cases)}] case-{case_id} {case['input'][:30]}... 执行中", file=sys.stderr)
            result = lead_main.execute_request(case["input"], gameplay_online=True)
        except Exception as e:
            # execute_request 已兜底大部分异常，这里防 runner 层意外
            result = {"run_id": "", "task_id": "", "ok": False,
                      "fail_reason": "runner_exception", "error": str(e),
                      "lead_plan": None, "gameplay_plan": None, "latency_ms": None}

        meta = {
            "case_id": case_id, "complexity": case.get("complexity", ""),
            "input": case["input"], "run_id": result["run_id"],
            "task_id": result["task_id"], "ok": result["ok"],
            "fail_reason": result.get("fail_reason", ""),
            "error": result.get("error", ""),
            "latency_ms": result.get("latency_ms"),
        }
        # 统计用记录：meta + 方案全文（结构完整率本地检查需要）
        record = dict(meta)
        record["lead_plan"] = result.get("lead_plan")
        record["gameplay_plan"] = result.get("gameplay_plan")
        results.append(record)

        # ---- 4. 存档证据 runs/<run_id>/ ----
        if result["run_id"]:
            run_dir = RUNS_DIR / result["run_id"]
            run_dir.mkdir(parents=True, exist_ok=True)
            with open(run_dir / "meta.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            if result.get("lead_plan"):
                with open(run_dir / "lead_plan.md", "w", encoding="utf-8") as f:
                    f.write(result["lead_plan"])
            if result.get("gameplay_plan"):
                with open(run_dir / "gameplay_plan.md", "w", encoding="utf-8") as f:
                    f.write(result["gameplay_plan"])
            # console.log：本条样例的状态摘要（完整过程见两端事件日志）
            with open(run_dir / "console.log", "w", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat(timespec='seconds')}] case {case_id} "
                        f"ok={result['ok']} fail={result.get('fail_reason', '')}\n")

        status = "✅" if result["ok"] else f"❌ {result.get('fail_reason', 'unknown')}"
        lat = f"{(result.get('latency_ms') or 0) / 1000:.1f}s" if result.get("latency_ms") else "-"
        print(f"[{idx}/{len(cases)}] case-{case_id} {status} 端到端 {lat}"
              + (f"  存档: {run_dir}" if run_dir else ""), file=sys.stderr)

    wall_cost = time.time() - wall_t0

    # ---- 5. 双端事件归并统计 ----
    run_ids = {r["run_id"] for r in results if r["run_id"]}
    task_ids = {r["task_id"] for r in results if r["task_id"]}
    ev_lead = [e for e in load_events(LEAD_EVENTS) if e.get("run_id") in run_ids]
    ev_game = [e for e in load_events(GAMEPLAY_EVENTS) if e.get("task_id") in task_ids]

    def cnt(evs, name):
        return sum(1 for e in evs if e.get("event") == name)

    n = len(results)
    ok_n = sum(1 for r in results if r["ok"])
    lead_ok = cnt(ev_lead, "lead_plan_ok")
    a2a_start = cnt(ev_lead, "a2a_send_start")
    a2a_done = cnt(ev_lead, "a2a_completed")
    artifact_saved = sum(1 for e in ev_lead
                         if e.get("event") == "artifact_saved" and e.get("state") == "completed")
    gp_start = cnt(ev_game, "task_start")
    gp_done = cnt(ev_game, "task_completed")

    # 耗时（各段事件自带 latency_ms；端到端取 ok 样本的全程）
    lat = lambda evs, name: [e.get("latency_ms") for e in evs
                             if e.get("event") == name and e.get("latency_ms") is not None]
    end2end_ms = [r["latency_ms"] for r in results if r["ok"] and r.get("latency_ms")]
    lead_ms = lat(ev_lead, "lead_plan_ok")
    a2a_ms = lat(ev_lead, "a2a_completed")
    gp_ms = lat(ev_game, "task_completed")

    # 结构完整率（分母=该方案实际生成成功的样本数）
    struct_gp_ok = sum(1 for r in results if r.get("gameplay_plan"))
    struct_gp_full = 0
    for r in results:
        if r.get("gameplay_plan") and check_structure(r["gameplay_plan"], game_secs)["complete"]:
            struct_gp_full += 1
    lead_plan_cnt = sum(1 for r in results if r.get("lead_plan"))
    struct_lead_full = 0
    for r in results:
        if r.get("lead_plan") and check_structure(r["lead_plan"], lead_secs)["complete"]:
            struct_lead_full += 1

    # ---- 6. 汇总打印 ----
    print("\n" + "=" * 64)
    print(f"汇总（{n} 条，总耗时 {wall_cost:.1f}s）")
    print("=" * 64)
    print(f"端到端任务完成率 : {pct(ok_n, n)}")
    print(f"任务流转成功率   : {pct(a2a_done, a2a_start)}  (A2A completed/递交)")
    print(f"漏斗  主策划生成 : {pct(lead_ok, n)}")
    print(f"       A2A递交   : {pct(a2a_start, lead_ok)}")
    print(f"       玩法生成   : {pct(gp_done, gp_start)}")
    print(f"       成果回传   : {pct(artifact_saved, a2a_done)}")
    print(f"结构   玩法方案   : {pct(struct_gp_full, struct_gp_ok)}  主策划方案: {pct(struct_lead_full, lead_plan_cnt)}")
    print(f"耗时   端到端     : {stat_ms(end2end_ms)}")
    print(f"        主策划生成 : {stat_ms(lead_ms)}")
    print(f"        A2A递交   : {stat_ms(a2a_ms)}")
    print(f"        玩法生成   : {stat_ms(gp_ms)}")

    fail_list = [r for r in results if not r["ok"]]
    if fail_list:
        print(f"\n失败 {len(fail_list)} 条：")
        for r in fail_list:
            print(f"  case-{r['case_id']} [{r['fail_reason']}] {r['error'][:100]}  run={r['run_id'][:8]}")

    # ---- 7. 生成报告 ----
    report = build_report(cfg, cases, results, ev_lead, ev_game, {
        "n": n, "ok_n": ok_n, "lead_ok": lead_ok, "a2a_start": a2a_start,
        "a2a_done": a2a_done, "artifact_saved": artifact_saved,
        "gp_start": gp_start, "gp_done": gp_done,
        "struct_gp_ok": struct_gp_ok, "struct_gp_full": struct_gp_full,
        "lead_plan_cnt": lead_plan_cnt, "struct_lead_full": struct_lead_full,
        "end2end_ms": end2end_ms, "lead_ms": lead_ms, "a2a_ms": a2a_ms, "gp_ms": gp_ms,
        "wall_cost": wall_cost, "online_detail": detail,
    })
    report_path = BENCH_DIR / REPORT_NAME
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已生成: {report_path}")
    print(f"样例存档目录: {RUNS_DIR}")
    return 0


def build_report(cfg, cases, results, ev_lead, ev_game, s) -> str:
    """组装 Markdown 报告（头部元数据 + 指标 + 失败明细 + 证据路径）"""
    now = datetime.now()
    lead_model = lead_temp = gp_model = gp_temp = "?"
    # 两端模型/温度从各自 .env 读取（仅取模型与温度字段，不涉及密钥）
    try:
        from dotenv import dotenv_values
        lv = dotenv_values(LEAD_DIR / ".env")
        gv = dotenv_values(GAMEPLAY_DIR / ".env")
        lead_model, lead_temp = lv.get("LLM_MODEL", "?"), lv.get("LLM_TEMPERATURE", "?")
        gp_model, gp_temp = gv.get("LLM_MODEL", "?"), gv.get("LLM_TEMPERATURE", "?")
    except Exception:
        pass

    L = []
    a = L.append
    a("# game_planning_studio A2A 量化测试报告")
    a("")
    a("## 一、元数据（数字只对以下配置下的观测负责）")
    a("")
    a(f"- 测试时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    a(f"- 运行环境：{platform.platform()} / Python {platform.python_version()}")
    a(f"- 部署形态：同机双进程（gameplay 服务 + lead 跑批），localhost A2A")
    a(f"- 主策划（lead_agent）：**{lead_model} @ temperature {lead_temp}**")
    a(f"- 玩法策划（gameplay_agent）：**{gp_model} @ temperature {gp_temp}**")
    a(f"- 测试集：{cfg['meta']['source']}（{cfg['meta']['case_count']} 条；本次执行 {s['n']} 条"
      + ("" if s['n'] == len(cases) else "（--limit 截断）") + "）")
    a(f"- 玩法策划探活：{s['online_detail']}")
    a(f"- 总耗时：{s['wall_cost']:.1f}s（含 20 条 LLM 生成）")
    a(f"- 启动命令：`uv run --project lead_agent python 量化测评/run_e2e_batch.py`")
    a("")
    a("## 二、指标结果")
    a("")
    a("| 指标 | 结果 |")
    a("|---|---|")
    a(f"| 端到端任务完成率 | {pct(s['ok_n'], s['n'])} |")
    a(f"| 任务流转成功率（A2A completed/递交） | {pct(s['a2a_done'], s['a2a_start'])} |")
    a("")
    a("### 阶段漏斗（定位断点）")
    a("")
    a("| 阶段 | 成功 | 进入 | 成功率 |")
    a("|---|---|---|---|")
    a(f"| A 主策划生成 | {s['lead_ok']} | {s['n']} | {pct(s['lead_ok'], s['n'])} |")
    a(f"| B A2A 递交返回 completed | {s['a2a_done']} | {s['a2a_start']} | {pct(s['a2a_done'], s['a2a_start'])} |")
    a(f"| C 玩法策划生成 | {s['gp_done']} | {s['gp_start']} | {pct(s['gp_done'], s['gp_start'])} |")
    a(f"| D 成果回传写盘 | {s['artifact_saved']} | {s['a2a_done']} | {pct(s['artifact_saved'], s['a2a_done'])} |")
    a("")
    a("### 耗时（生成成功的样本，s）")
    a("")
    a("| 段 | min / avg / max |")
    a("|---|---|")
    a(f"| 端到端全程 | {stat_ms(s['end2end_ms'])} |")
    a(f"| 主策划生成 | {stat_ms(s['lead_ms'])} |")
    a(f"| A2A 递交+玩法生成+回传 | {stat_ms(s['a2a_ms'])} |")
    a(f"| 玩法策划生成（服务端） | {stat_ms(s['gp_ms'])} |")
    a("")
    a("### 方案结构完整率（本地规则检查，零 LLM 成本）")
    a("")
    a(f"- 玩法策划方案（含核心循环/战斗或操作/成长/数值/玩法亮点全部章节）：**{pct(s['struct_gp_full'], s['struct_gp_ok'])}**")
    a(f"- 主策划方案（含游戏概述/核心定位/系统框架/差异化/开发建议全部章节）：{pct(s['struct_lead_full'], s['lead_plan_cnt'])}（参考）")
    a("")
    a("## 三、失败明细")
    a("")
    fails = [r for r in results if not r["ok"]]
    if fails:
        a("| case | 失败分类 | 错误 | 存档 |")
        a("|---|---|---|---|")
        for r in fails:
            a(f"| case-{r['case_id']} | {r['fail_reason']} | {r['error'][:120] or '-'} | `runs/{r['run_id']}/` |")
    else:
        a("无（全部走通）。")
    a("")
    a("## 四、证据留存（可复现）")
    a("")
    a("- 测试集：`量化测评/e2e_cases.yaml`")
    a(f"- 主策划事件日志：`lead_agent/logs/events.jsonl`（本次 {len(ev_lead)} 条）")
    a(f"- 玩法策划事件日志：`gameplay_agent/logs/events.jsonl`（本次 {len(ev_game)} 条）")
    a("- 每条样例存档：`量化测评/runs/<run_id>/`（meta.json + lead_plan.md + gameplay_plan.md）")
    a("- 口径说明：只测 A2A 主链路；玩法策划必须在线；不做自动重试；失败均为一次通过率口径")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
