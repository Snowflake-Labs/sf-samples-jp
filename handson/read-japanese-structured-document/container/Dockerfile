# ジョブイメージ（S30・S50・S60）。
# ビルドはローカルで行う：scripts/build_push.sh（docker buildx build --platform linux/amd64）
# 依存は uv.lock から書き出した container/requirements.lock で固定する（ローカルのテストと同じ版）。
# データセット・ローカル設定・正解由来の shot はイメージに入れない（.dockerignore）。
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONHASHSEED=0 \
    JPDOCREAD_HOME=/app JPDOCREAD_WORK=/tmp/jpdocread/work JPDOCREAD_OUT=/tmp/jpdocread/out

WORKDIR /app
COPY container/requirements.lock /app/container/requirements.lock
RUN pip install --no-cache-dir -r /app/container/requirements.lock

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY configs /app/configs
RUN pip install --no-cache-dir --no-deps /app \
    && python -c "import jpdocread.jobs, jpdocread.read.integrate, jpdocread.eval.evaluate" \
    && python -m jpdocread guard \
    && test ! -e /app/configs/deploy.local.env && test ! -e /app/configs/shots \
    && useradd --create-home --uid 1000 jpdocread \
    && mkdir -p /tmp/jpdocread && chown jpdocread /tmp/jpdocread

USER jpdocread
ENTRYPOINT ["python", "-m", "jpdocread"]
CMD ["--help"]
