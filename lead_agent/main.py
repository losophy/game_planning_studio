# lead_agent/main.py

import os
import uuid
import yaml
import requests
from pathlib import Path
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

def send_plan_to_gameplay(plan_content: str, plan_file: str):
    """通过标准A2A协议（JSON-RPC tasks/send）发送方案给玩法策划Agent"""
    task_id = str(uuid.uuid4())
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
    try:
        response = requests.post(GAMEPLAY_URI, json=payload, timeout=300)
        data = response.json()

        if data.get("error"):
            print(f"\n❌ A2A调用失败: {data['error'].get('message', data['error'])}")
            return False

        task = data.get("result") or {}
        state = (task.get("status") or {}).get("state", "unknown")

        if state == "completed":
            print(f"\n✅ 方案已递交给玩法策划")
            print(f"   任务ID: {task_id}")

            # 从 Artifact 中取玩法策划方案全文
            artifacts = task.get("artifacts") or []
            for artifact in artifacts:
                for part in artifact.get("parts", []):
                    if part.get("kind") == "text" and part.get("text"):
                        gameplay_output = OUTPUT_DIR / config["output"]["gameplay_plan"]
                        with open(gameplay_output, 'w', encoding='utf-8') as f:
                            f.write(part["text"])
                        print(f"   玩法策划的方案已同步带回一份")
                        return True
            return True
        else:
            msg = ((task.get("status") or {}).get("message") or {})
            detail = "".join(p.get("text", "") for p in msg.get("parts", []))
            print(f"\n❌ 玩法策划任务未完成: {state} {detail}")
            return False

    except requests.exceptions.ConnectionError:
        print(f"\n❌ 找不到玩法策划: {GAMEPLAY_URI}")
        print("   可能还没到工位，稍后再试")
        return False
    except Exception as e:
        print(f"\n❌ 递交方案时出错: {e}")
        return False

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
        gameplay_online = True
    else:
        print("⚠️ 玩法策划还没到工位")
        print("   主策划方案会先做出来，等玩法策划到位后再补玩法设计")
        gameplay_online = False
    
    # 获取用户输入
    user_input = input("\n老板，你想做什么游戏: ").strip()
    if not user_input:
        user_input = "我想做一个二次元风格的卡牌RPG手游"
    
    print(f"\n需求: {user_input}")
    print("=" * 60)
    print("正在分析需求...")
    print("=" * 60)
    
    # 运行主策划Agent
    result = lead_designer.invoke({
        "messages": [{"role": "user", "content": user_input}]
    })
    
    # 提取输出（取最后一条消息，即Agent的最终回答，不要取第一条=用户输入）
    output_content = result["messages"][-1].content
    
    # 保存到文件
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / config["output"]["lead_plan"]
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(output_content)
    
    print(f"\n✅ 主策划方案已完成，存放在: {output_file}")
    
    # 显示方案摘要
    print("\n" + "=" * 60)
    print("主策划方案摘要")
    print("=" * 60)
    
    print(summarize_md(output_content, show_sections=False))
    
    # 发送方案给玩法策划
    if gameplay_online:
        print("\n" + "=" * 60)
        print("正在把方案递交给玩法策划...")
        print("=" * 60)
        
        send_plan_to_gameplay(output_content, str(output_file))
    else:
        print("\n" + "=" * 60)
        print("提示")
        print("=" * 60)
        print("玩法策划还没到工位，主策划方案先存档。")
        print("等玩法策划到位后，重新运行本主策划即可补上玩法设计。")
    
    print("\n✅ 主策划交稿完成！")

if __name__ == "__main__":
    main()
