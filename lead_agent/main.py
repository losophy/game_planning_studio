# lead_agent/main.py

import os
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
            "gameplay_uri": "http://localhost:8080/receive_plan",
            "gameplay_health_uri": "http://localhost:8080/health"
        },
        "output": {"dir": "./output", "lead_plan": "主策划方案.md", "gameplay_plan": "玩法策划方案.md"}
    }

config = load_config()
OUTPUT_DIR = BASE_DIR / config["output"]["dir"]
GAMEPLAY_URI = config["lead_agent"]["gameplay_uri"]
GAMEPLAY_HEALTH_URI = config["lead_agent"].get(
    "gameplay_health_uri",
    GAMEPLAY_URI.replace("/receive_plan", "/health")
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
    """检查玩法策划Agent是否在线"""
    try:
        # 使用配置中的健康检查URI（不再用字符串替换推导）
        response = requests.get(GAMEPLAY_HEALTH_URI, timeout=5)
        if response.status_code == 200:
            return True, response.json()
    except Exception:
        pass
    return False, None

# ===================== 发送方案给玩法策划 =====================
def send_plan_to_gameplay(plan_content: str, plan_file: str):
    """通过HTTP接口发送方案给玩法策划Agent"""
    try:
        response = requests.post(
            GAMEPLAY_URI,
            json={
                "plan_content": plan_content,
                "plan_file": plan_file
            },
            timeout=300  # DeepSeek生成长文档可能超过60秒，放宽超时
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"\n✅ 已成功发送方案给玩法策划Agent")
            print(f"   玩法策划方案将保存到: {result.get('output_file', '未知')}")
            
            # 如果返回了方案内容，保存到本地
            if "plan_content" in result:
                gameplay_output = OUTPUT_DIR / config["output"]["gameplay_plan"]
                with open(gameplay_output, 'w', encoding='utf-8') as f:
                    f.write(result["plan_content"])
                print(f"   已同步保存到本地: {gameplay_output}")
            
            return True
        else:
            print(f"\n❌ 发送方案失败: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"\n❌ 无法连接到玩法策划Agent: {GAMEPLAY_URI}")
        print("   请确保玩法策划Agent已启动并且网络可达")
        return False
    except Exception as e:
        print(f"\n❌ 发送方案时出错: {e}")
        return False

# ===================== 主程序 =====================
def main():
    print("=" * 60)
    print("AI游戏策划工作室 - 主策划Agent")
    print("=" * 60)
    
    # 显示配置信息
    print()
    print("配置信息:")
    print(f"  玩法策划URI: {GAMEPLAY_URI}")
    print(f"  输出目录: {OUTPUT_DIR}")
    
    # 检查玩法策划Agent
    print("\n正在检查玩法策划Agent状态...")
    is_online, info = check_gameplay_agent()
    
    if is_online:
        print("✅ 玩法策划Agent已在线")
        print(f"   URI: {info.get('uri', '未知')}")
        gameplay_online = True
    else:
        print("⚠️ 玩法策划Agent未启动或不可达")
        print("   方案将只保存到文件，不会自动发送给玩法策划")
        gameplay_online = False
    
    # 获取用户输入
    user_input = input("\n请输入你的游戏想法: ").strip()
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
    
    print(f"\n✅ 主策划方案已保存到: {output_file}")
    
    # 显示方案摘要
    print("\n" + "=" * 60)
    print("主策划方案摘要")
    print("=" * 60)
    
    lines = output_content.split('\n')
    for line in lines[:15]:
        if line.strip():
            print(line)
    
    # 发送方案给玩法策划
    if gameplay_online:
        print("\n" + "=" * 60)
        print("正在发送方案给玩法策划Agent...")
        print("=" * 60)
        
        send_plan_to_gameplay(output_content, str(output_file))
    else:
        print("\n" + "=" * 60)
        print("提示")
        print("=" * 60)
        print("玩法策划Agent未启动，方案已保存到文件。")
        print("如需玩法策划分析，请：")
        print("1. 先启动玩法策划Agent（gameplay_agent 目录下 uv run python main.py）")
        print("2. 再重新运行主策划Agent")
    
    print("\n✅ 主策划Agent工作完成！")

if __name__ == "__main__":
    main()
