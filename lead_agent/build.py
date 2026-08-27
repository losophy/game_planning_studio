# lead_agent/build.py
# 在 lead_agent 目录下运行：uv run python build.py
# 前置：uv tool install pyinstaller（全局工具，一次即可）
# 产物输出到本目录 dist/lead_agent/，与 exe 同级带上 config.yaml、skills/、.env

import shutil
import subprocess
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
AGENT_NAME = "lead_agent"

def build_exe():
    """使用PyInstaller打包 lead_agent（config.yaml / skills/ / .env 不打进 exe，
    而是复制到 exe 同级目录，便于外部修改配置与模型）"""
    cmd = [
        "pyinstaller",  # 全局工具：uv tool install pyinstaller
        "--onefile",
        "--name", AGENT_NAME,
        "--distpath", str(AGENT_DIR / "dist"),
        str(AGENT_DIR / "main.py")
    ]
    subprocess.run(cmd, check=True)

    # 将 config.yaml、skills/、.env 复制到 dist/ 下与 exe 同级
    dist_dir = AGENT_DIR / "dist" / AGENT_NAME
    dist_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(AGENT_DIR / "config.yaml", dist_dir / "config.yaml")
    shutil.copytree(AGENT_DIR / "skills", dist_dir / "skills", dirs_exist_ok=True)
    env_src = AGENT_DIR / ".env"
    if env_src.exists():
        shutil.copy2(env_src, dist_dir / ".env")
    print(f"✅ {AGENT_NAME}.exe 打包完成")
    print(f"   已复制 config.yaml、skills/ 和 .env 到 {dist_dir}")

if __name__ == "__main__":
    build_exe()
