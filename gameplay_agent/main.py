# gameplay_agent/main.py

import os
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

# ===================== Flask应用 =====================
app = Flask(__name__)

# 静音开发服务器的技术日志（WARNING、banner、Running on、请求日志等）
logging.getLogger('werkzeug').setLevel(logging.ERROR)
logging.getLogger('flask.cli').setLevel(logging.ERROR)
# Flask 的 banner（"Serving Flask app / Debug mode"）不走 logging，直接替换为空函数
import flask.cli
flask.cli.show_server_banner = lambda *args, **kwargs: None

@app.route('/health', methods=['GET'])
def health():
    """健康检查接口"""
    return jsonify({
        "status": "running",
        "agent": "gameplay_designer",
        "uri": config["gameplay_agent"]["uri"]
    })

@app.route('/receive_plan', methods=['POST'])
def receive_plan():
    """接收主策划方案的接口"""
    try:
        data = request.json
        plan_content = data.get('plan_content', '')
        plan_file = data.get('plan_file', '')
        
        print("\n" + "=" * 60)
        print("收到主策划方案！")
        print("=" * 60)
        
        # 如果提供了文件路径，从文件读取
        if plan_file:
            # 支持跨电脑：如果文件路径不存在，使用plan_content
            if Path(plan_file).exists():
                with open(plan_file, 'r', encoding='utf-8') as f:
                    plan_content = f.read()
                print(f"从本地文件读取方案: {plan_file}")
            else:
                print("使用HTTP传输的方案内容")
        
        if not plan_content:
            return jsonify({"error": "未收到方案内容"}), 400
        
        print("\n主策划方案内容:")
        print("-" * 60)
        print(plan_content[:500] + "..." if len(plan_content) > 500 else plan_content)
        print("-" * 60)
        
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
        
        lines = output_content.split('\n')
        for line in lines[:20]:
            if line.strip():
                print(line)
        
        print("\n✅ 玩法策划Agent工作完成！")
        
        return jsonify({
            "status": "success",
            "message": "玩法策划方案已生成",
            "output_file": str(output_file),
            "plan_content": output_content  # 返回方案内容供主策划显示
        })
        
    except Exception as e:
        print(f"\n❌ 处理方案时出错: {e}")
        return jsonify({"error": str(e)}), 500

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
