# 给支持 Docker 的平台用：Koyeb、Back4App、Northflank、自建 VPS……
# Render 用原生 Python 环境即可，不需要这个文件（但用 Docker 也能跑）。

FROM python:3.13-slim

WORKDIR /app

# 本项目零依赖，不需要 pip install，直接把代码拷进去就能跑
COPY . .

ENV PYTHONUNBUFFERED=1 \
    LHT_HOST=0.0.0.0

# 平台注入 PORT 时会自动采用（server.py 优先读 LHT_PORT，其次 PORT）；
# 不注入则退回 8766。
EXPOSE 8766

CMD ["python", "server.py"]
