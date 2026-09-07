FROM ghcr.io/james-6-23/codex2api:latest

USER root

# 从官方 Redis 镜像拷贝 redis-server / redis-cli
COPY --from=redis:7-alpine /usr/local/bin/redis-server /usr/local/bin/redis-server
COPY --from=redis:7-alpine /usr/local/bin/redis-cli /usr/local/bin/redis-cli

# 安装运行 Redis 所需依赖
RUN apk add --no-cache libstdc++ tzdata ca-certificates

WORKDIR /app

COPY --chmod=755 entrypoint.sh /app/entrypoint.sh

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=30s \
  CMD wget -q -T 5 -O /dev/null http://127.0.0.1:7860/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]