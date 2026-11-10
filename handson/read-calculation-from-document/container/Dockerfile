# 予測ジョブのイメージ（linux/amd64・非 root）。ビルドは scripts/build_push.sh。
# 依存は uv.lock から書き出した container/requirements.lock で固定する（ローカルのテストと同じ版）。
# データセット・正解・手本・ローカル設定・資格情報はイメージに入れない（.dockerignore と下の検査）。
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONHASHSEED=0 \
    JPCALC_HOME=/app JPCALC_WORK=/tmp/jpcalc/work JPCALC_OUT=/tmp/jpcalc/out

WORKDIR /app
COPY container/requirements.lock /app/container/requirements.lock
RUN pip install --no-cache-dir -r /app/container/requirements.lock

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY configs /app/configs
COPY sql /app/sql
RUN pip install --no-cache-dir --no-deps /app \
    && python -c "import jpcalc.jobs, jpcalc.predict.pipeline, jpcalc.pdfread.pdoc" \
    && python -m jpcalc guard \
    && test ! -e /app/configs/deploy.local.env && test ! -e /app/configs/shots && test ! -e /app/data && test ! -e /app/eval_data \
    && test ! -e /app/work && test ! -e /app/out \
    && useradd --create-home --uid 1000 jpcalc \
    && mkdir -p /tmp/jpcalc && chown jpcalc /tmp/jpcalc

USER jpcalc
ENTRYPOINT ["python", "-m", "jpcalc"]
CMD ["--help"]
