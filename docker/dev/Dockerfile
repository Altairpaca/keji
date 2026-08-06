# 开发容器镜像：仅用于本地开发。
# 生产镜像（W12 里程碑）将做非 root 用户、依赖锁定、多阶段构建等强化。

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libpq 头文件供 psycopg 编译（binary wheel 一般已内置，保留以备源码构建）；
# build-essential 供可能需要的 C 扩展编译。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
