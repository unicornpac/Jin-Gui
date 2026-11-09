#!/bin/bash
set -e

echo "======================================"
echo "  金匮要略临床思辨训练系统 - 启动脚本"
echo "======================================"

# -- Render 持久磁盘初始化 --
if [ -n "$DATA_DIR" ]; then
    echo "[磁盘] 持久数据目录: $DATA_DIR"
    mkdir -p "$DATA_DIR/uploads"

    # 首次部署：拷贝种子数据库到持久磁盘
    if [ ! -f "$DATA_DIR/tcm.db" ]; then
        if [ -f "data/tcm.db" ]; then
            cp data/tcm.db "$DATA_DIR/tcm.db"
            echo "[磁盘] 已拷贝种子数据库到持久磁盘"
        else
            echo "[磁盘] 未找到种子数据库，将自动创建"
        fi
    else
        echo "[磁盘] 数据库已存在，跳过初始化"
    fi

    # 首次部署：拷贝 uploads 文件到持久磁盘（后续上传的新文件在此持久化）
    if [ -d "uploads" ]; then
        cp -rn uploads/* "$DATA_DIR/uploads/" 2>/dev/null || true
    fi
else
    echo "[磁盘] 本地模式，使用仓库内 data/ 目录"
fi

# -- 安装依赖 --
echo "[依赖] 安装 Python 包..."
pip install -r requirements.txt -q 2>&1 | tail -1

# -- 种子数据（幂等，已存在则跳过）--
echo "[数据] 运行种子脚本..."
python seed_cases.py
python seed_texts.py

# -- 启动服务 --
PORT="${PORT:-8000}"
echo "[服务] 启动于 0.0.0.0:$PORT"
echo "======================================"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
