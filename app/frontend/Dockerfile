# 前端镜像：Nginx 托管构建产物并反向代理 /api。
# 构建目录里已有 dist/（deploy/build.sh 在本机构建过）就直接使用；否则在镜像内联网安装依赖并构建，本机无需 Node.js。
FROM node:22-slim AS build
WORKDIR /web
COPY . .
RUN if [ -f dist/index.html ]; then echo "使用已构建的 dist/"; else npm ci && npm run build; fi

FROM nginx:1.30
COPY --from=build /web/dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
