#!/bin/sh
# 首次启动数据库时创建两个账号：app_owner 拥有表、只给迁移；app_runtime 给 web 运行（技术方案 §5.1.3）。
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<SQL
CREATE ROLE app_owner LOGIN PASSWORD '${APP_OWNER_PASSWORD}' CREATEDB;
CREATE ROLE app_runtime LOGIN PASSWORD '${APP_RUNTIME_PASSWORD}';
CREATE DATABASE jh OWNER app_owner;
SQL
