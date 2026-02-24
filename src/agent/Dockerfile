FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Runtime code depends on boto3/reportlab.
RUN pip install --no-cache-dir "boto3>=1.34,<2" "reportlab>=4,<5"

COPY . /app/agent

# Keep container alive with an HTTP server that handles /invocations.
CMD ["python", "-m", "agent.server"]
