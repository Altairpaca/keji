# nginx 生产镜像：在官方 nginx:1.27-alpine 基础上创建与 web 应用同 UID 的用户。
# 应用以 mkstemp→rename 原子写媒体文件（0600，仅属主可读），
# nginx worker 需与 app 同 UID 才能读取 media/static 卷，同时保持非世界可读。

FROM nginx:1.27-alpine

RUN addgroup -g 1001 app \
    && adduser -D -u 1001 -G app app

# 配置由 compose 以只读卷挂载（docker/prod/nginx.conf）。
