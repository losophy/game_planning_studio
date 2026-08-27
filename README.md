# AI游戏策划工作室

基于 LangChain + Flask 的双 Agent 协作系统：**主策划Agent** 从"老板一句话"产出主策划方案，通过 HTTP（简化版A2A）把方案交给 **玩法策划Agent**，产出玩法策划方案。支持同机与跨电脑运行。

## 目录结构

```
game_planning_studio/
├── 主策划Agent/          # 主策划Agent（命令行交互）
│   ├── main.py
│   ├── config.yaml
│   ├── skills/
│   │   ├── need_analysis/     # 共享技能（与玩法策划各带一份）
│   │   └── project_planning/
│   └── requirements.txt
├── 玩法策划Agent/        # 玩法策划Agent（HTTP服务）
│   ├── main.py
│   ├── config.yaml
│   ├── skills/
│   │   ├── need_analysis/     # 共享技能
│   │   ├── core_loop/
│   │   ├── combat_system/
│   │   └── numerical_balance/
│   └── requirements.txt
├── shared/skills/        # 共享技能源（改动后同步到两个Agent）
├── build.py              # PyInstaller打包脚本
├── .env                  # API Key（勿提交）
└── README.md
```

## 快速开始

### 1. 配置 API Key

编辑根目录 `.env`：

```
DEEPSEEK_API_KEY=sk-你的Key
```

### 2. 安装依赖

```bash
cd 主策划Agent
pip install -r requirements.txt

cd ../玩法策划Agent
pip install -r requirements.txt
```

### 3. 同一台电脑运行

```bash
# 终端1：启动玩法策划Agent（先启动，监听8080端口）
python 玩法策划Agent/main.py

# 终端2：启动主策划Agent，输入游戏想法
python 主策划Agent/main.py
```

输出文件在各自 Agent 的 `output/` 目录：
- `主策划Agent/output/主策划方案.md`
- `玩法策划Agent/output/玩法策划方案.md`

### 4. 跨电脑运行

1. 电脑B（玩法策划）：`ipconfig` 查看本机IP，把 `玩法策划Agent/config.yaml` 中 `uri` 改为该IP，启动。
2. 电脑A（主策划）：把 `主策划Agent/config.yaml` 中 `gameplay_uri` / `gameplay_health_uri` 改为电脑B的IP，启动。
3. 注意防火墙放行8080端口（见方案第9章）。

## 打包为exe

```bash
pip install pyinstaller
python build.py
```

产物在 `dist/`，每个 exe 同级目录会自动带上 `config.yaml` 和 `skills/`，分发时需一并拷贝。

## 方案文档

完整设计文档见 `AI游戏策划工作室搭建方案.md`（v6.1）。
