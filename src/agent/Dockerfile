# 以官方 Python 3.11 slim 镜像作为基础运行环境
FROM python:3.11-slim

# 设置容器内工作目录
WORKDIR /app

# 将当前构建上下文（src/agent）复制到容器内的包目录
COPY . /app/agent

# 容器启动命令：运行 agent.app 模块
CMD ["python", "-m", "agent.app"]
