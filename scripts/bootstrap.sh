#!/bin/bash
# K8S NetLab 快速启动脚本
set -euo pipefail

echo "=========================================="
echo "  K8S NetLab 快速启动"
echo "=========================================="
echo ""

# 【1/6】检查Python版本
echo "【1/6】检查Python版本..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then
    echo "✅ Python $PYTHON_VERSION"
else
    echo "❌ 需要Python 3.10+，当前: $PYTHON_VERSION"
    exit 1
fi

# 【2/6】检查配置文件
echo ""
echo "【2/6】检查配置文件..."
if [ ! -f .env ]; then
    echo "⚠️  .env 文件不存在，从 .env.example 创建..."
    cp .env.example .env
    echo ""
    echo "⚠️  请编辑 .env 文件，填写实际配置："
    echo "   nano .env"
    echo ""
    read -p "配置完成后按回车继续..."
else
    echo "✅ .env 已存在"
fi

# 【3/6】创建虚拟环境
echo ""
echo "【3/6】创建虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ 虚拟环境已创建"
else
    echo "✅ 虚拟环境已存在"
fi

# 激活虚拟环境
# shellcheck disable=SC1091
source venv/bin/activate

# 【4/6】安装依赖
echo ""
echo "【4/6】安装依赖..."
pip install --upgrade pip -q
pip install -r requirements.txt
echo "✅ 依赖安装完成"

# 【5/6】创建数据目录
echo ""
echo "【5/6】创建数据目录..."
mkdir -p data logs
chmod 700 data
echo "✅ 目录已就绪"

# 【6/6】启动服务
echo ""
echo "【6/6】启动服务..."

PORT=$(grep "^APP_PORT=" .env | cut -d'=' -f2)
PORT=${PORT:-8000}

if command -v ss &>/dev/null && ss -tuln 2>/dev/null | grep -q ":$PORT "; then
    echo "⚠️  端口 $PORT 已被占用，请修改 .env 中的 APP_PORT"
    exit 1
fi

python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" --reload &
BACKEND_PID=$!

echo ""
echo "=========================================="
echo "  ✅ K8S NetLab 启动成功！"
echo "=========================================="
echo ""
echo "访问地址: http://localhost:$PORT"
echo "后端 PID: $BACKEND_PID"
echo ""
echo "停止服务: kill $BACKEND_PID"
echo "查看日志: tail -f logs/k8s-netlab.log"
echo ""
