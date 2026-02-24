# 选择精简版 Python 3.11 作为基础镜像，减小体积
FROM python:3.11-slim

# 不生成 .pyc 文件，避免容器内无意义写入
ENV PYTHONDONTWRITEBYTECODE=1
# 标准输出不做缓冲，日志可以实时看到
ENV PYTHONUNBUFFERED=1

# 容器工作目录
WORKDIR /app

# 先复制依赖清单，利用 Docker 分层缓存
COPY requirements.txt /app/requirements.txt
# 安装运行依赖
RUN pip install --no-cache-dir -r /app/requirements.txt

# 复制应用代码
COPY . /app/agent

# 启动内置 HTTP 服务，对外提供 /invocations
CMD ["python", "-m", "agent.server"]
