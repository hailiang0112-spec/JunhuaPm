# 后端镜像：Python 3.13 + Gunicorn。依赖从 wheelhouse/ 离线安装（构建前执行 deploy/build.sh 下载）。
# 备份容器复用本镜像，需要 pg_dump / pg_restore：从同为 Debian 13 的 postgres:18 镜像拷贝客户端及其依赖库。
FROM postgres:18 AS pgclient
RUN mkdir -p /out/bin /out/lib && cp /usr/lib/postgresql/18/bin/pg_dump /usr/lib/postgresql/18/bin/pg_restore /usr/lib/postgresql/18/bin/psql /out/bin/ \
 && for b in /out/bin/*; do ldd "$b" | awk '/=> \//{print $3}'; done | sort -u | xargs -I{} cp -L {} /out/lib/

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
COPY --from=pgclient /out/bin/ /usr/local/bin/
COPY --from=pgclient /out/lib/ /usr/local/lib/pgclient/
RUN echo /usr/local/lib/pgclient > /etc/ld.so.conf.d/zz-pgclient.conf && ldconfig && pg_dump --version
WORKDIR /app
COPY wheelhouse/ /wheelhouse/
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheelhouse -r requirements.txt && rm -rf /wheelhouse
COPY . .
RUN rm -rf .venv data staticfiles wheelhouse && chmod +x entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["web"]
