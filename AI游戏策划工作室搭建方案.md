# AI游戏策划工作室搭建方案

> 本文件为**设计文档**，不含代码实现。代码见项目内对应文件：
> - 主策划Agent：`lead_agent/main.py`
> - 玩法策划Agent：`gameplay_agent/main.py`

## 一、方案概述

### 1.1 核心理念

基于AI智能体技术栈（LangChain + LangGraph），构建一个从"老板一句话"到"完整策划文档包"的多智能体协作系统。采用**两个独立Agent + 简化版A2A（自定义HTTP接口）**的简洁架构，支持跨电脑协作。

> **术语说明**：本方案的"简化版A2A"指基于已知URI的自定义HTTP通信（POST JSON收发方案），未实现标准A2A协议（Agent Card发现、Task状态跟踪等，见资料库第26章）。它足以满足两个固定Agent的跨电脑协作场景；如需对接异构Agent系统，再升级为标准A2A。

### 1.2 架构特点

| 特点 | 说明 |
|------|------|
| **独立进程** | 两个Agent各自独立启动（uv run） |
| **已知URI** | 通过配置文件指定玩法策划Agent的URI |
| **跨电脑** | 支持不同电脑之间的HTTP通信（简化版A2A） |
| **HTTP服务** | 玩法策划提供HTTP接口，主策划调用发送 |
| **用户启动** | 两个Agent都由用户手动启动 |
| **md输出** | 方案输出为Markdown格式 |

### 1.3 工作流程

```
【场景：跨电脑协作】

电脑B：启动玩法策划Agent（uv run python main.py）
    ↓
玩法策划Agent启动HTTP服务（端口8080）
    ↓
用户配置主策划Agent的URI

电脑A：启动主策划Agent（uv run python main.py）
    ↓
输入游戏需求
    ↓
主策划Agent分析需求
    ↓
输出主策划方案到本地md文件
    ↓
通过配置的URI调用玩法策划Agent
    ↓
玩法策划Agent收到方案，开始分析
    ↓
输出玩法策划方案到本地md文件
```

---

## 二、系统架构

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    AI游戏策划工作室                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  【电脑A】                          【电脑B】               │
│  ┌─────────────────────┐           ┌─────────────────────┐ │
│  │  主策划Agent进程    │           │  玩法策划Agent进程  │ │
│  │                     │           │                     │ │
│  │  用户输入           │           │  启动HTTP服务       │ │
│  │      ↓              │   HTTP    │      ↓              │ │
│  │  需求分析           │ ───────→  │  等待接收方案       │ │
│  │      ↓              │           │      ↓              │ │
│  │  输出方案.md        │           │  分析玩法设计       │ │
│  │                     │           │      ↓              │ │
│  │                     │           │  输出玩法方案.md    │ │
│  └─────────────────────┘           └─────────────────────┘ │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    通信方式                          │   │
│  │  主策划Agent通过配置的URI调用玩法策划Agent           │   │
│  │  URI示例: http://192.168.1.100:8080/receive_plan    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
game_planning_studio/
├── lead_agent/
│   ├── main.py              # 主策划Agent主程序
│   ├── config.yaml          # 配置文件
│   ├── pyproject.toml       # 本Agent依赖声明（uv）
│   ├── .env                 # 本Agent模型配置（独立于其他Agent）
│   ├── skills/              # 主策划Skills
│   │   ├── need_analysis/   # 共享技能（与玩法策划各带一份）
│   │   │   └── SKILL.md
│   │   └── project_planning/
│   │       └── SKILL.md
│   └── uv.lock              # uv sync 自动生成
├── gameplay_agent/
│   ├── main.py              # 玩法策划Agent主程序（含HTTP服务）
│   ├── config.yaml          # 配置文件
│   ├── pyproject.toml       # 本Agent依赖声明（uv）
│   ├── .env                 # 本Agent模型配置（独立于其他Agent）
│   ├── skills/              # 玩法策划Skills
│   │   ├── need_analysis/   # 共享技能（与主策划各带一份）
│   │   │   └── SKILL.md
│   │   ├── core_loop/
│   │   │   └── SKILL.md
│   │   ├── combat_system/
│   │   │   └── SKILL.md
│   │   └── numerical_balance/
│   │       └── SKILL.md
│   └── uv.lock              # uv sync 自动生成
├── shared/
│   └── skills/              # 共享Skills源（改动后需同步到两个Agent）
│       └── need_analysis/
│           └── SKILL.md
└── README.md
```

---

## 三、配置文件设计

### 3.1 主策划Agent配置

```yaml
# lead_agent/config.yaml

# 玩法策划Agent配置（需要填写实际的URI）
lead_agent:
  # 玩法策划Agent的URI（用于发送方案）
  # 如果是同一台电脑: http://localhost:8080/receive_plan
  # 如果是不同电脑: http://192.168.1.100:8080/receive_plan
  gameplay_uri: "http://localhost:8080/receive_plan"
  # 玩法策划Agent的健康检查URI（显式配置，避免字符串替换推导）
  gameplay_health_uri: "http://localhost:8080/health"

# 输出配置
output:
  dir: "./output"
  lead_plan: "主策划方案.md"
  gameplay_plan: "玩法策划方案.md"
```

### 3.2 玩法策划Agent配置

```yaml
# gameplay_agent/config.yaml

# 服务配置
gameplay_agent:
  # 服务端口
  port: 8080
  # 公网/局域网URI（用于跨电脑通信）
  # 如果是同一台电脑: http://localhost:8080
  # 如果是不同电脑: http://192.168.1.100:8080
  uri: "http://localhost:8080"

# 输出配置
output:
  dir: "./output"
  gameplay_plan: "玩法策划方案.md"
```

---

## 四、主策划Agent设计

### 4.1 职责

1. **需求分析**：从用户描述中提取核心要素
2. **方向把控**：确定游戏定位、目标用户、核心卖点
3. **框架搭建**：设计整体游戏框架和系统结构
4. **决策建议**：给出明确的方向性建议

### 4.2 关键设计点

| 设计点 | 说明 |
|--------|------|
| Agent创建 | `create_agent`（LangChain V1.x），system_prompt 注入需求分析与项目规划两个Skill |
| 模型接入 | `ChatOpenAI` + DeepSeek（`base_url` + `api_key` + `model`） |
| 健康检查 | 启动时探测玩法策划 `gameplay_health_uri`，离线则只出主策划方案 |
| 方案下发 | 通过 `gameplay_uri` POST 主策划方案，`timeout=300` |
| 输出提取 | 取 `result["messages"][-1]`（最后一条AIMessage），避免取到用户输入 |
| 输出保存 | Markdown 写入本地 `output/` 目录 |

### 4.3 工作流程

```
启动 → 检查玩法策划在线状态 → 输入游戏想法
    → 主策划Agent生成方案 → 保存md → 发送给玩法策划 → 结束
```

---

## 五、玩法策划Agent设计

### 5.1 职责

1. **核心循环**：设计玩家主要行为循环
2. **战斗/操作机制**：设计核心操作和战斗系统
3. **成长系统**：设计角色/装备/技能成长路径
4. **数值框架**：设计基础数值体系和平衡原则

### 5.2 关键设计点

| 设计点 | 说明 |
|--------|------|
| Agent创建 | `create_agent`，system_prompt 注入需求分析、核心循环、战斗系统、数值平衡四个Skill |
| HTTP服务 | Flask，`threaded=True` 支持并发；`host='0.0.0.0'` 支持跨电脑访问 |
| 健康检查 | `GET /health` 返回服务状态与URI |
| 方案接收 | `POST /receive_plan` 接收主策划方案，跨电脑时优先用 HTTP 传输内容 |
| 输出提取 | 同主策划，取 `result["messages"][-1]` |
| 结果回传 | 返回 `plan_content`，主策划可同步保存到本地 |

### 5.3 HTTP接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查，返回 `status/agent/uri` |
| `/receive_plan` | POST | 接收主策划方案，返回 `status/output_file/plan_content` |

---

## 六、Skills设计

### 6.1 共享Skills目录

```
shared/
└── skills/              # 共享Skills源目录
    └── need_analysis/
        └── SKILL.md
```

> **说明**：`need_analysis` 是主策划与玩法策划共享的技能。修改 `shared/skills/need_analysis/SKILL.md` 后，需同步复制到两个Agent各自的 `skills/need_analysis/` 目录。

### 6.2 需求分析Skill

```markdown
---
name: need-analysis
description: 当用户提供游戏项目需求描述时，提取核心要素。两个策划Agent共享此技能。
---

# 需求分析技能

## 角色定位
你是资深游戏策划需求分析师，擅长从模糊描述中提取关键信息。

## 触发边界
- 用户提供游戏项目的一句话描述或初步想法
- 需要明确游戏类型、目标用户、核心玩法等要素

## 执行步骤
1. 阅读用户提供的需求描述
2. 提取核心要素：类型、平台、玩法、用户、卖点
3. 标注每个要素的明确程度
4. 输出结构化需求文档

## 输出格式
- 游戏类型：[明确/待确认]
- 目标平台：[明确/待确认]
- 核心玩法：[明确/待确认]
- 目标用户：[明确/待确认]
- 差异化卖点：[明确/待确认]
```

### 6.3 主策划专属Skills

#### 项目规划Skill

```markdown
---
name: project-planning
description: 当需要统筹游戏项目方向、设计整体框架时使用。
---

# 项目规划技能

## 角色定位
你是资深主策划，擅长从宏观角度把握游戏项目方向。

## 触发边界
- 需要确定游戏整体定位
- 需要设计系统框架
- 需要在多个方案中做决策

## 执行步骤
1. 基于需求分析结果，确定游戏定位
2. 设计核心玩法框架
3. 规划系统结构
4. 定义差异化设计
5. 输出完整项目方案

## 输出格式
### 游戏概述
[一句话描述游戏核心体验]

### 核心定位
- 类型：[游戏类型]
- 平台：[目标平台]
- 用户：[目标用户]

### 系统框架
[主要系统及其关系图]

### 差异化设计
- 创新点：[创新设计]
- 记忆点：[让玩家记住的设计]
```

### 6.4 玩法策划专属Skills

#### 核心循环Skill

```markdown
---
name: core-loop
description: 当需要设计游戏核心行为循环时使用。
---

# 核心循环设计技能

## 角色定位
你是资深玩法策划，专注于设计让玩家上瘾的核心循环。

## 触发边界
- 需要设计玩家主要行为流
- 需要定义核心游戏机制
- 需要确保游戏有持续吸引力

## 执行步骤
1. 分析游戏类型的核心体验
2. 设计单次游戏循环
3. 设计长期留存循环
4. 验证循环的吸引力
5. 输出核心循环图

## 输出格式
### 单次循环
[玩家一次游戏的行为流]

### 长期循环
[玩家长期留存的动力设计]

### 循环验证
- 新手体验：[是否容易上手]
- 中期目标：[是否有持续动力]
- 长期追求：[是否有深度可挖]
```

#### 战斗系统Skill

```markdown
---
name: combat-system
description: 当需要设计游戏战斗或操作机制时使用。
---

# 战斗系统设计技能

## 角色定位
你是资深战斗系统设计师，擅长设计有趣且平衡的战斗机制。

## 触发边界
- 需要设计战斗系统
- 需要设计操作机制
- 需要设计技能系统

## 执行步骤
1. 确定战斗类型（回合制/即时制/...）
2. 设计核心操作
3. 设计技能体系
4. 设计敌人AI
5. 验证战斗节奏

## 输出格式
### 战斗类型
[回合制/即时制/自动战斗/...]

### 核心操作
[玩家的主要操作方式]

### 技能体系
[技能分类、释放方式、组合效果]

### 敌人设计
[敌人类型、AI行为、难度曲线]
```

#### 数值平衡Skill

```markdown
---
name: numerical-balance
description: 当需要设计游戏数值体系和平衡性时使用。
---

# 数值平衡设计技能

## 角色定位
你是资深数值策划，擅长设计平衡且有趣的数值体系。

## 触发边界
- 需要设计属性体系
- 需要设计成长曲线
- 需要确保数值平衡

## 执行步骤
1. 定义核心属性
2. 设计属性关系
3. 设计成长曲线
4. 设计经济系统
5. 验证数值平衡

## 输出格式
### 属性体系
[主要属性及其作用]

### 成长曲线
[等级/属性成长公式]

### 经济系统
[货币产出/消耗设计]

### 平衡原则
[数值设计的核心原则]
```

### 6.5 Skills加载方式说明（进阶）

本方案采用**全量注入**：启动时把所有 SKILL.md 直接拼进 system_prompt，实现简单、适合入门。

进阶方向（参考资料库27章"渐进式加载"）：改为只把各技能的 `name + description` 索引注入 system_prompt，由模型判断命中后再读取完整 SKILL.md。当技能数量增多（>5个）或单个SKILL.md很长时，建议升级为渐进式加载，可节省token并提升指令精度。

---

## 七、使用方式

### 7.1 安装依赖与环境配置

每个 Agent 目录下各有独立的 `.env`（不同 Agent 可用不同 LLM），配置项：

```bash
# lead_agent/.env 与 gameplay_agent/.env（各自独立填写）

# LLM配置（OpenAI兼容接口）
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=你的Key
# 兼容旧字段 DEEPSEEK_API_KEY
```

```bash
# 1. 安装主策划Agent依赖（uv，自动创建 .venv 与 uv.lock）
cd lead_agent
uv sync

# 2. 安装玩法策划Agent依赖
cd ../gameplay_agent
uv sync
```

### 7.2 同一台电脑使用

```bash
# 1. 配置玩法策划Agent
# gameplay_agent/config.yaml
gameplay_agent:
  port: 8080
  uri: "http://localhost:8080"

# 2. 配置主策划Agent
# lead_agent/config.yaml
lead_agent:
  gameplay_uri: "http://localhost:8080/receive_plan"
  gameplay_health_uri: "http://localhost:8080/health"

# 3. 启动玩法策划Agent（先启动，它要监听HTTP端口）
uv run python gameplay_agent/main.py

# 4. 启动主策划Agent
uv run python lead_agent/main.py
```

### 7.3 跨电脑使用

```bash
# 电脑B（玩法策划Agent）
# 1. 查看本机IP
ipconfig  # Windows
ifconfig  # Linux/Mac

# 2. 配置玩法策划Agent
# gameplay_agent/config.yaml
gameplay_agent:
  port: 8080
  uri: "http://192.168.1.100:8080"  # 电脑B的IP

# 3. 启动玩法策划Agent
uv run python main.py

# 电脑A（主策划Agent）
# 1. 配置主策划Agent
# lead_agent/config.yaml
lead_agent:
  gameplay_uri: "http://192.168.1.100:8080/receive_plan"  # 电脑B的IP
  gameplay_health_uri: "http://192.168.1.100:8080/health"  # 电脑B的IP

# 2. 启动主策划Agent
uv run python main.py
```

### 7.4 输出示例

```
============================================================
AI游戏策划工作室 - 主策划Agent
============================================================

配置信息:
  玩法策划URI: http://192.168.1.100:8080/receive_plan
  输出目录: ./output

正在检查玩法策划Agent状态...
✅ 玩法策划Agent已在线
   URI: http://192.168.1.100:8080

请输入你的游戏想法: 我想做一个二次元风格的卡牌RPG手游

需求: 我想做一个二次元风格的卡牌RPG手游
============================================================
正在分析需求...
============================================================

✅ 主策划方案已保存到: ./output/主策划方案.md

============================================================
主策划方案摘要
============================================================
# 游戏设计文档 - 《星渊录》

## 游戏概述
一款以星际幻想为背景的二次元卡牌RPG手游

## 核心定位
- 类型：卡牌RPG
- 平台：移动端（iOS/Android）

============================================================
正在发送方案给玩法策划Agent...
============================================================

✅ 已成功发送方案给玩法策划Agent
   玩法策划方案将保存到: ./output/玩法策划方案.md

✅ 主策划Agent工作完成！
```

---

## 八、依赖管理（uv）

项目使用 [uv](https://docs.astral.sh/uv/) 管理依赖，每个 Agent 独立环境、各自声明依赖。

### 8.1 依赖声明

```toml
# lead_agent/pyproject.toml
[project]
name = "lead-agent"
version = "0.1.0"
description = "主策划Agent"
requires-python = ">=3.10"
dependencies = [
    "langchain>=1.0.0",
    "langchain-openai>=0.3.0",
    "python-dotenv",
    "requests",
    "pyyaml",
]

# gameplay_agent/pyproject.toml
[project]
name = "gameplay-agent"
version = "0.1.0"
description = "玩法策划Agent"
requires-python = ">=3.10"
dependencies = [
    "langchain>=1.0.0",
    "langchain-openai>=0.3.0",
    "python-dotenv",
    "flask",
    "pyyaml",
]
```

### 8.2 安装与运行

```bash
# 安装依赖（各自目录下执行，自动创建 .venv 与 uv.lock）
cd lead_agent
uv sync

cd ../gameplay_agent
uv sync

# 启动玩法策划Agent（先启动，监听8080端口）
cd ../gameplay_agent
uv run python main.py

# 启动主策划Agent（另一个终端）
cd ../lead_agent
uv run python main.py
```

---

## 九、网络配置说明

### 9.1 防火墙配置

```bash
# Windows（管理员权限运行）
netsh advfirewall firewall add rule name="游戏策划Agent" dir=in action=allow protocol=TCP localport=8080

# Linux
sudo ufw allow 8080/tcp

# macOS
sudo pfctl -e
# 编辑 /etc/pf.conf 添加:
# pass in proto tcp from any to any port 8080
```

### 9.2 路由器配置（跨局域网）

如果需要跨局域网通信，需要：
1. 配置端口转发（8080端口）
2. 使用动态DNS服务
3. 或者使用内网穿透工具（如frp、ngrok）

---

## 十、技术栈总结

| 组件 | 技术 | 参考章节 |
|------|------|----------|
| Agent创建 | `create_agent` | 21章 |
| 模型接入 | `ChatOpenAI` | 11章 |
| Skills | `SKILL.md` | 27章 |
| A2A通信 | HTTP (Flask) + 已知URI（简化版A2A） | 26章（概念参考） |
| 输出格式 | Markdown | - |
| 依赖管理 | uv（pyproject.toml + uv.lock） | - |

---

## 十一、总结

### 11.1 方案特点

| 特点 | 说明 |
|------|------|
| **独立进程** | 两个Agent各自独立启动（uv run） |
| **已知URI** | 通过配置文件指定玩法策划Agent的URI |
| **跨电脑** | 支持不同电脑之间的HTTP通信（简化版A2A） |
| **HTTP服务** | 玩法策划提供HTTP接口，主策划调用发送 |
| **用户启动** | 两个Agent都由用户手动启动 |
| **md输出** | 方案输出为Markdown格式 |

### 11.2 使用流程

```
1. 配置玩法策划Agent的URI（config.yaml）
2. 配置主策划Agent的玩法策划URI（config.yaml）
3. 启动玩法策划Agent（uv run，启动HTTP服务，等待）
4. 启动主策划Agent（uv run，输入需求，输出方案，调用玩法策划）
5. 查看 output/ 目录下的两个md文件
```

---

*方案版本：v6.1（设计文档版，代码见项目文件）*
*技术栈：LangChain + Flask + Python + uv*
