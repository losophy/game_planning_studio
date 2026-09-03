# lead_agent/main.py

import os
import uuid
import yaml
import requests
from pathlib import Path
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from metrics import log_event, now_ms

# ===================== 路径与环境 =====================
def get_base_dir() -> Path:
    """基础目录：脚本所在目录（config.yaml 与 .env 与脚本同级）"""
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()

# .env：与本Agent的 config.yaml 同级
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

# ===================== 配置加载 =====================
def load_config():
    """加载配置文件"""
    config_path = BASE_DIR / "config.yaml"
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {
        "lead_agent": {
            "gameplay_uri": "http://localhost:8080/",
            "gameplay_card_uri": "http://localhost:8080/.well-known/agent.json"
        },
        "output": {"dir": "./output", "lead_plan": "主策划方案.md", "gameplay_plan": "玩法策划方案.md"}
    }

config = load_config()
OUTPUT_DIR = BASE_DIR / config["output"]["dir"]
GAMEPLAY_URI = config["lead_agent"]["gameplay_uri"]
GAMEPLAY_CARD_URI = config["lead_agent"].get(
    "gameplay_card_uri",
    GAMEPLAY_URI.rstrip("/") + "/.well-known/agent.json"
)

# ===================== 模型初始化 =====================
# 模型相关配置统一从本Agent的 .env 读取，不同Agent可使用不同LLM
def get_llm():
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),  # 主策划 DeepSeek-V3.2 推荐 0.7
    )

# ===================== Skills加载 =====================
def load_skill(skill_path: str) -> str:
    """加载SKILL.md文件"""
    full_path = BASE_DIR / skill_path
    if full_path.exists():
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

# 加载专属Skills
NEED_ANALYSIS_SKILL = load_skill("skills/need_analysis/SKILL.md")
PROJECT_PLANNING_SKILL = load_skill("skills/project_planning/SKILL.md")

# ===================== 主策划Agent定义 =====================
LEAD_DESIGNER_PROMPT = f"""你是资深主策划，负责统筹游戏项目方向。

{NEED_ANALYSIS_SKILL}

{PROJECT_PLANNING_SKILL}

## 你的职责
1. **需求分析**：从用户描述中提取核心要素
2. **方向把控**：确定游戏定位、目标用户、核心卖点
3. **框架搭建**：设计整体游戏框架和系统结构
4. **决策建议**：给出明确的方向性建议

## 输出格式
用Markdown格式输出，包含以下部分：

### 游戏概述
[一句话描述游戏核心体验]

### 核心定位
- 类型：[游戏类型]
- 平台：[目标平台]
- 用户：[目标用户画像]

### 系统框架
[主要系统及其关系，用简洁的结构图或列表表示]

### 差异化设计
- 创新点：[1-2个创新设计]
- 记忆点：[让玩家记住的设计]

### 开发建议
- 预估周期：[基于项目规模]
- 关键风险：[需要重点关注的点]

## 重要规则
- 输出必须是Markdown格式
- 保持专业性但不过度技术化
- 每次都完整输出所有部分
"""

# 创建主策划Agent
lead_designer = create_agent(
    model=get_llm(),
    tools=[],
    name="lead_designer",
    system_prompt=LEAD_DESIGNER_PROMPT,
)

# ===================== 检查玩法策划Agent =====================
def check_gameplay_agent():
    """读取玩法策划的Agent Card，确认其在线并返回能力信息（A2A发现）"""
    try:
        response = requests.get(GAMEPLAY_CARD_URI, timeout=5)
        if response.status_code == 200:
            card = response.json()
            return True, {
                "name": card.get("name", "未知"),
                "description": card.get("description", ""),
                "url": card.get("url", GAMEPLAY_URI),
            }
    except Exception:
        pass
    return False, None

# ===================== 发送方案给玩法策划 =====================
def summarize_md(md_text: str, show_sections: bool = True) -> str:
    """提取md方案的简短摘要（纯本地，无LLM调用）：
    文档标题 + 游戏概述（或首个章节）首句 + 章节列表（可选）。
    兼容 # / ## / ### 任意标题层级。"""
    lines = md_text.strip().split("\n")
    doc_title = ""
    sections = []
    overview = ""
    current = ""            # 当前章节名
    seen_overview = False   # 是否出现过"游戏概述"章节
    first_section = ""      # 第一个章节名（无游戏概述时兜底用）

    for line in lines:
        s = line.strip()
        if s.startswith("# "):
            if not doc_title:
                doc_title = s[2:].strip()
        elif s.startswith("## ") or s.startswith("### "):
            name = s.lstrip("#").strip()
            if not first_section:
                first_section = name
            sections.append(name)
            current = name
            if name == "游戏概述":
                seen_overview = True
        elif not overview and s and not s.startswith(("- ", "* ", "`", "|", ">")):
            # 正文行：在"游戏概述"内，或在没有游戏概述时的首个章节内
            if current == "游戏概述" or (not seen_overview and current == first_section):
                overview = s[:60]

    summary = []
    if doc_title:
        summary.append(f"📄 {doc_title}")
    if overview:
        summary.append(f"💡 {overview}")
    if show_sections and sections:
        summary.append("📑 " + " / ".join(sections[:8]))
    return "\n".join(summary) if summary else md_text[:100]

def send_plan_to_gameplay(plan_content: str, run_id: str) -> dict:
    """通过标准A2A协议（JSON-RPC tasks/send）发送方案给玩法策划Agent（带事件打点）。

    返回 dict：
      ok            端到端成功（返回 completed 且玩法方案文本写盘成功）
      task_id       A2A 任务 id（归并键之一）
      gameplay_text 玩法方案全文（成功时有值）
      fail_reason   失败分类（a2a_failed_* / artifact_missing / artifact_saved_failed）
      error         具体错误文本
      latency_ms    递交+回传段耗时（毫秒）
    """
    task_id = str(uuid.uuid4())
    t0 = now_ms()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tasks/send",
        "params": {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [
                    {"kind": "text", "text": f"基于以下主策划方案，进行深入的玩法设计：\n\n{plan_content}"}
                ]
            }
        }
    }
    log_event(agent="lead", run_id=run_id, task_id=task_id,
              event="a2a_send_start", state="submitted")

    try:
        response = requests.post(GAMEPLAY_URI, json=payload, timeout=300)
        data = response.json()
    except requests.exceptions.ConnectionError as e:
        latency = now_ms() - t0
        log_event(agent="lead", run_id=run_id, task_id=task_id,
                  event="a2a_failed_offline", state="failed",
                  error=str(e), latency_ms=round(latency, 1))
        print(f"\n❌ 找不到玩法策划: {GAMEPLAY_URI}")
        print("   可能还没到工位，稍后再试")
        return {"ok": False, "task_id": task_id, "gameplay_text": "",
                "fail_reason": "a2a_failed_offline", "error": str(e),
                "latency_ms": round(latency, 1)}
    except Exception as e:
        latency = now_ms() - t0
        log_event(agent="lead", run_id=run_id, task_id=task_id,
                  event="a2a_failed_unknown", state="failed",
                  error=str(e), latency_ms=round(latency, 1))
        print(f"\n❌ 递交方案时出错: {e}")
        return {"ok": False, "task_id": task_id, "gameplay_text": "",
                "fail_reason": "a2a_failed_unknown", "error": str(e),
                "latency_ms": round(latency, 1)}

    latency = now_ms() - t0

    if data.get("error"):
        msg = data["error"].get("message", data["error"])
        log_event(agent="lead", run_id=run_id, task_id=task_id,
                  event="a2a_failed_jsonrpc", state="failed",
                  error=str(msg), latency_ms=round(latency, 1))
        print(f"\n❌ A2A调用失败: {msg}")
        return {"ok": False, "task_id": task_id, "gameplay_text": "",
                "fail_reason": "a2a_failed_jsonrpc", "error": str(msg),
                "latency_ms": round(latency, 1)}

    task = data.get("result") or {}
    state = (task.get("status") or {}).get("state", "unknown")

    if state != "completed":
        msg = (task.get("status") or {}).get("message") or {}
        detail = "".join(p.get("text", "") for p in msg.get("parts", []))
        log_event(agent="lead", run_id=run_id, task_id=task_id,
                  event="a2a_failed_state", state=state,
                  error=f"{state} {detail}".strip(), latency_ms=round(latency, 1))
        print(f"\n❌ 玩法策划任务未完成: {state} {detail}")
        return {"ok": False, "task_id": task_id, "gameplay_text": "",
                "fail_reason": "a2a_failed_state",
                "error": f"{state} {detail}".strip(),
                "latency_ms": round(latency, 1)}

    # state == completed：递交流转成功，从 Artifact 中提取玩法策划方案全文
    log_event(agent="lead", run_id=run_id, task_id=task_id,
              event="a2a_completed", state="completed", latency_ms=round(latency, 1))
    print(f"\n✅ 方案已递交给玩法策划")
    print(f"   任务ID: {task_id}")
    artifacts = task.get("artifacts") or []
    text = ""
    for artifact in artifacts:
        for part in artifact.get("parts", []):
            if part.get("kind") == "text" and part.get("text"):
                text = part["text"]
                break
        if text:
            break

    if not text:
        log_event(agent="lead", run_id=run_id, task_id=task_id,
                  event="artifact_missing", state="completed",
                  error="completed 但 artifacts 无 text part",
                  latency_ms=round(latency, 1))
        print("\n❌ 玩法策划返回 completed 但未带回方案文本（artifact_missing）")
        return {"ok": False, "task_id": task_id, "gameplay_text": "",
                "fail_reason": "artifact_missing",
                "error": "completed 但无 text artifact",
                "latency_ms": round(latency, 1)}

    # 写盘
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        gameplay_output = OUTPUT_DIR / config["output"]["gameplay_plan"]
        with open(gameplay_output, 'w', encoding='utf-8') as f:
            f.write(text)
        log_event(agent="lead", run_id=run_id, task_id=task_id,
                  event="artifact_saved", state="completed",
                  latency_ms=round(latency, 1))
        print(f"   玩法策划的方案已同步带回一份: {gameplay_output}")
        return {"ok": True, "task_id": task_id, "gameplay_text": text,
                "fail_reason": "", "error": "",
                "latency_ms": round(latency, 1)}
    except Exception as e:
        log_event(agent="lead", run_id=run_id, task_id=task_id,
                  event="artifact_saved", state="failed",
                  error=f"写盘失败: {e}", latency_ms=round(latency, 1))
        return {"ok": False, "task_id": task_id, "gameplay_text": text,
                "fail_reason": "artifact_saved_failed", "error": str(e),
                "latency_ms": round(latency, 1)}

# ===================== 执行一轮端到端请求 =====================
def execute_request(user_input: str, gameplay_online: bool | None = None) -> dict:
    """执行一轮完整流程：需求 → 主策划方案 → A2A 递交 → 玩法方案回传写盘。

    CLI 入口（main）与批量 runner（量化测评/run_e2e_batch.py）共用同一函数，
    保证手工与批量两种跑法走完全相同的代码路径。

    参数：
    - user_input:      老板的需求文本
    - gameplay_online: 玩法策划是否在线；None 表示内部探活一次（main 已探活则传入避免重复请求）
    返回 dict：
      run_id / task_id / ok / fail_reason / error / lead_plan / gameplay_plan / latency_ms
      （ok=True 表示端到端完成：主策划方案落盘 + A2A completed + 玩法方案写盘成功）
    """
    run_id = str(uuid.uuid4())
    t0 = now_ms()
    log_event(agent="lead", run_id=run_id, event="request_start")

    # 探活（可由调用方注入结果，避免重复请求）
    if gameplay_online is None:
        gameplay_online, _info = check_gameplay_agent()
    log_event(agent="lead", run_id=run_id,
              event="discovery_ok" if gameplay_online else "discovery_fail",
              state="online" if gameplay_online else "offline")

    # ---- 1. 主策划方案（invoke 包 try/except，异常不再崩进程）----
    try:
        t1 = now_ms()
        result = lead_designer.invoke({
            "messages": [{"role": "user", "content": user_input}]
        })
        # 取最后一条消息=Agent 最终回答（第一条是用户输入）
        lead_plan = result["messages"][-1].content
        log_event(agent="lead", run_id=run_id, event="lead_plan_ok",
                  state="completed", latency_ms=round(now_ms() - t1, 1))
    except Exception as e:
        log_event(agent="lead", run_id=run_id, event="lead_plan_fail",
                  state="failed", error=str(e),
                  latency_ms=round(now_ms() - t1, 1))
        print(f"\n❌ 主策划方案生成失败: {e}")
        return {"run_id": run_id, "task_id": "", "ok": False,
                "fail_reason": "lead_plan_fail", "error": str(e),
                "lead_plan": None, "gameplay_plan": None,
                "latency_ms": round(now_ms() - t0, 1)}

    # ---- 2. 主策划方案落盘（CLI 既有行为；runner 另行存档副本）----
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / config["output"]["lead_plan"]
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(lead_plan)
    print(f"\n✅ 主策划方案已完成，存放于: {output_file}")

    # ---- 3. A2A 递交 ----
    if not gameplay_online:
        # 本测评口径：玩法策划必须在线；离线"降级产出"不计为端到端成功
        print("\n⚠️ 玩法策划还没到工位，主策划方案先存档。")
        return {"run_id": run_id, "task_id": "", "ok": False,
                "fail_reason": "a2a_failed_discovery",
                "error": "玩法策划不在线（测评口径不计为成功）",
                "lead_plan": lead_plan, "gameplay_plan": None,
                "latency_ms": round(now_ms() - t0, 1)}

    print("\n" + "=" * 60)
    print("正在把方案递交给玩法策划...")
    print("=" * 60)
    send = send_plan_to_gameplay(lead_plan, run_id)
    return {"run_id": run_id, "task_id": send["task_id"],
            "ok": send["ok"], "fail_reason": send["fail_reason"],
            "error": send["error"],
            "lead_plan": lead_plan,
            "gameplay_plan": send["gameplay_text"] or None,
            "latency_ms": round(now_ms() - t0, 1)}


# ===================== 主程序 =====================
def main():
    print("=" * 60)
    print("本主策划已到工位，听候老板差遣")
    print("=" * 60)
    print()
    print("我的职责：")
    print("1. 需求分析：从老板的话里提炼游戏核心要素")
    print("2. 方向把控：定下游戏类型、目标用户和核心卖点")
    print("3. 框架搭建：设计整体游戏框架和系统结构")
    print("4. 决策建议：给出明确的方向性建议")
    print()
    print("老板给个想法，我来把大方向定下来，再交给玩法策划细化。")
    print()
    print("按 Ctrl+C 下班")
    print("=" * 60)
    print()

    # 检查玩法策划Agent
    print("正在检查玩法策划是否在工位...")
    is_online, info = check_gameplay_agent()

    if is_online:
        print("✅ 玩法策划已在工位")
        print(f"   工位地址: {info.get('url', GAMEPLAY_URI)}")
    else:
        print("⚠️ 玩法策划还没到工位")
        print("   主策划方案会先做出来，等玩法策划到位后再补玩法设计")

    # 获取用户输入
    user_input = input("\n老板，你想做什么游戏: ").strip()
    if not user_input:
        user_input = "我想做一个二次元风格的卡牌RPG手游"

    print(f"\n需求: {user_input}")
    print("=" * 60)
    print("正在分析需求...")
    print("=" * 60)

    # 执行一轮端到端流程（传入已探活的在线状态，避免重复探活）
    result = execute_request(user_input, gameplay_online=is_online)

    print("\n" + "=" * 60)
    if result["ok"]:
        print("✅ 主策划交稿完成！")
        print("\n主策划方案摘要")
        print("=" * 60)
        print(summarize_md(result["lead_plan"], show_sections=False))
        gameplay_file = OUTPUT_DIR / config["output"]["gameplay_plan"]
        print(f"\n玩法策划方案已同步回传: {gameplay_file}")
    else:
        print(f"❌ 本轮未走通（{result['fail_reason']}）")
        if result["error"]:
            print(f"   原因: {result['error'][:200]}")
        if result["lead_plan"]:
            print("\n主策划方案摘要（已存档，待玩法策划补设计）")
            print("=" * 60)
            print(summarize_md(result["lead_plan"], show_sections=False))
    print("=" * 60)

if __name__ == "__main__":
    main()
