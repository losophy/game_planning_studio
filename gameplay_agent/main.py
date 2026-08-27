# gameplay_agent/main.py

import os
import uuid
import logging
import yaml
from pathlib import Path
from flask import Flask, request, jsonify
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

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
        "gameplay_agent": {"port": 8080, "uri": "http://localhost:8080"},
        "output": {"dir": "./output", "gameplay_plan": "玩法策划方案.md"}
    }

config = load_config()
OUTPUT_DIR = BASE_DIR / config["output"]["dir"]
HTTP_PORT = config["gameplay_agent"]["port"]

# ===================== 模型初始化 =====================
# 模型相关配置统一从本Agent的 .env 读取，不同Agent可使用不同LLM
def get_llm():
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        api_key=os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        temperature=0.7,
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
CORE_LOOP_SKILL = load_skill("skills/core_loop/SKILL.md")
COMBAT_SYSTEM_SKILL = load_skill("skills/combat_system/SKILL.md")
NUMERICAL_BALANCE_SKILL = load_skill("skills/numerical_balance/SKILL.md")

# ===================== 玩法策划Agent定义 =====================
GAMEPLAY_DESIGNER_PROMPT = f"""你是资深玩法策划，专注于游戏核心机制设计。

{NEED_ANALYSIS_SKILL}

{CORE_LOOP_SKILL}

{COMBAT_SYSTEM_SKILL}

{NUMERICAL_BALANCE_SKILL}

## 你的职责
1. **核心循环**：设计玩家主要行为循环
2. **战斗/操作机制**：设计核心操作和战斗系统
3. **成长系统**：设计角色/装备/技能成长路径
4. **数值框架**：设计基础数值体系和平衡原则

## 输入
你会收到主策划的方案，请基于主策划的方向进行深入的玩法设计。

## 输出格式
用Markdown格式输出，包含以下部分：

### 核心循环
[玩家主要行为流，描述玩家"做什么"]

### 战斗/操作机制
[核心操作方式、战斗系统设计]

### 成长系统
[角色/装备/技能如何成长]

### 数值框架
- 属性体系：[主要属性定义]
- 核心公式：[伤害/经验/经济等公式框架]
- 平衡原则：[数值设计的核心原则]

### 玩法亮点
[让玩法有深度、有记忆点的设计]

## 重要规则
- 输出必须是Markdown格式
- 基于主策划的方向进行设计，保持一致性
- 每次都完整输出所有部分
"""

# 创建玩法策划Agent
gameplay_designer = create_agent(
    model=get_llm(),
    tools=[],
    name="gameplay_designer",
    system_prompt=GAMEPLAY_DESIGNER_PROMPT,
)

# ===================== 方案摘要 =====================
def summarize_md(md_text: str) -> str:
    """提取md方案的简短摘要（纯本地，无LLM调用）：
    文档标题 + 游戏概述（或首个章节）首句 + 章节列表。
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
    if sections:
        summary.append("📑 " + " / ".join(sections[:8]))
    return "\n".join(summary) if summary else md_text[:100]

# ===================== Flask应用 =====================
app = Flask(__name__)

# 静音开发服务器的技术日志（WARNING、banner、Running on、请求日志等）
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('flask.cli').setLevel(logging.ERROR)
# Flask 的 banner（"Serving Flask app / Debug mode"）不走 logging，直接替换为空函数
import flask.cli
flask.cli.show_server_banner = lambda *args, **kwargs: None

# ===================== A2A 协议（标准 Agent-to-Agent） =====================
# 任务存储：task_id -> Task 对象（内存版，重启即清）
TASK_STORE = {}

# 基础URI：Agent Card 中声明的服务地址
AGENT_URL = config["gameplay_agent"]["uri"]

def agent_card() -> dict:
    """A2A Agent Card：能力名片，供调用方发现与握手"""
    return {
        "name": "gameplay_designer",
        "description": "玩法策划Agent：基于主策划方案进行深入的核心玩法设计",
        "url": AGENT_URL,
        "version": "1.0.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False
        },
        "skills": [
            {
                "id": "gameplay_design",
                "name": "玩法策划设计",
                "description": "输入主策划方案（Markdown），输出玩法策划方案（核心循环/战斗机制/成长系统/数值框架）",
                "tags": ["game-design", "gameplay", "game-planning"],
                "examples": ["基于主策划方案，进行深入的玩法设计"]
            }
        ],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "defaultSkillId": "gameplay_design"
    }

def make_task(task_id: str, state: str, message_text: str,
              artifacts: list | None = None) -> dict:
    """构造 A2A Task 对象"""
    return {
        "id": task_id,
        "status": {
            "state": state,  # submitted / working / completed / failed / canceled
            "message": {"role": "agent", "parts": [{"kind": "text", "text": message_text}]},
            "timestamp": __import__("datetime").datetime.now().isoformat()
        },
        "artifacts": artifacts or [],
        "messages": []
    }

def handle_tasks_send(params: dict) -> dict:
    """tasks/send：接收任务并执行玩法策划，返回 Task"""
    task_id = params.get("id") or str(uuid.uuid4())
    message = params.get("message") or {}

    # 从 A2A Message 的 parts 中提取文本内容
    plan_content = ""
    for part in message.get("parts", []):
        if part.get("kind") == "text" and part.get("text"):
            plan_content = part["text"]
            break

    if not plan_content:
        raise ValueError("未收到方案内容（message.parts 缺少 text part）")

    print("\n收到主策划的方案")
    print("=" * 60)

    # 先登记为 working
    TASK_STORE[task_id] = make_task(task_id, "working", "正在分析玩法设计...")
    try:
        # 运行玩法策划Agent
        print("\n正在分析玩法设计...")
        result = gameplay_designer.invoke({
            "messages": [{"role": "user", "content": f"基于以下主策划方案，进行深入的玩法设计：\n\n{plan_content}"}]
        })

        # 提取输出（取最后一条消息，即Agent的最终回答，不要取第一条=用户输入）
        output_content = result["messages"][-1].content

        # 保存到文件
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_file = OUTPUT_DIR / config["output"]["gameplay_plan"]

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)

        print(f"\n✅ 玩法策划方案已保存到: {output_file}")

        # 显示方案摘要
        print("\n" + "=" * 60)
        print("玩法策划方案摘要")
        print("=" * 60)
        print(summarize_md(output_content))
        print("\n✅ 玩法策划Agent工作完成！")

        # 构造完成状态的 Task，含 Artifact
        task = make_task(task_id, "completed", "玩法策划方案已生成")
        task["artifacts"] = [{
            "name": "玩法策划方案",
            "description": "玩法策划Agent产出的完整方案（Markdown）",
            "parts": [{"kind": "text", "text": output_content}],
            "metadata": {"output_file": str(output_file)}
        }]
        TASK_STORE[task_id] = task
        return task

    except Exception as e:
        print(f"\n❌ 处理方案时出错: {e}")
        task = make_task(task_id, "failed", f"处理方案时出错: {e}")
        TASK_STORE[task_id] = task
        return task

def handle_tasks_get(params: dict) -> dict:
    """tasks/get：按 task_id 查询任务状态"""
    task_id = params.get("id")
    if not task_id:
        raise ValueError("缺少任务 id")
    task = TASK_STORE.get(task_id)
    if not task:
        raise KeyError(f"任务不存在: {task_id}")
    return task

# JSON-RPC 方法分发
JSONRPC_METHODS = {
    "initialize": lambda params: agent_card(),
    "tasks/send": handle_tasks_send,
    "tasks/get": handle_tasks_get,
}

@app.route('/.well-known/agent.json', methods=['GET'])
def well_known_agent():
    """A2A Agent Card 发现端点"""
    return jsonify(agent_card())

@app.route('/', methods=['POST'])
def a2a_endpoint():
    """A2A JSON-RPC 2.0 端点"""
    try:
        data = request.get_json(silent=True) or {}
        method = data.get("method")
        params = data.get("params") or {}
        rpc_id = data.get("id")

        if method not in JSONRPC_METHODS:
            return jsonify({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}
            }), 200

        result = JSONRPC_METHODS[method](params)
        return jsonify({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    except ValueError as e:
        return jsonify({
            "jsonrpc": "2.0",
            "id": data.get("id") if 'data' in dir() else None,
            "error": {"code": -32602, "message": str(e)}
        }), 200
    except KeyError as e:
        return jsonify({
            "jsonrpc": "2.0",
            "id": data.get("id") if 'data' in dir() else None,
            "error": {"code": -32004, "message": str(e)}
        }), 200
    except Exception as e:
        return jsonify({
            "jsonrpc": "2.0",
            "id": data.get("id") if 'data' in dir() else None,
            "error": {"code": -32603, "message": f"Internal error: {e}"}
        }), 200

@app.route('/health', methods=['GET'])
def health():
    """健康检查接口"""
    return jsonify({
        "status": "running",
        "agent": "gameplay_designer",
        "uri": config["gameplay_agent"]["uri"]
    })

def run_flask():
    """运行Flask服务"""
    app.run(host='0.0.0.0', port=HTTP_PORT, debug=False, threaded=True)

# ===================== 主程序 =====================
def main():
    print("=" * 60)
    print("本玩法策划已到工位，等待主策划发送方案")
    print("=" * 60)
    print()
    print("我的职责：")
    print("1. 核心循环：设计玩家主要行为循环")
    print("2. 战斗/操作机制：设计核心操作和战斗系统")
    print("3. 成长系统：设计角色/装备/技能成长路径")
    print("4. 数值框架：设计基础数值体系和平衡原则")
    print()
    print("收到主策划的方案后，我会基于他的方向进行深入的玩法设计。")
    print()
    print("按 Ctrl+C 下班")
    print("=" * 60)

    # 启动HTTP服务
    run_flask()

if __name__ == "__main__":
    main()
