# 前端镜像：Nginx 托管构建产物并反向代理 /api。构建前先在本机执行 npm ci && npm run build。
FROM nginx:1.30
COPY dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
