#!/bin/sh
# 构建：在有网络的机器上下载后端依赖到 wheelhouse/、构建前端，再构建镜像（镜像构建过程不联网）。
set -e
cd "$(dirname "$0")/.."
rm -rf backend/wheelhouse && mkdir -p backend/wheelhouse
pip download -q -r backend/requirements.txt -d backend/wheelhouse \
  --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --platform any \
  --python-version 3.13 --implementation cp --only-binary=:all:
(cd frontend && npm ci && npm run build)
cd deploy && docker compose build
echo "构建完成"
