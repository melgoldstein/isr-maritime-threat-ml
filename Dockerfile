FROM python:3.12-slim AS builder
WORKDIR /opt/isr
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir '.[service]'
RUN python -m src.pipeline --output /opt/isr/artifacts --tracks /opt/isr/synthetic.csv
RUN python -c "import json,shutil; from pathlib import Path; manifest=json.loads(Path('artifacts/run_manifest.json').read_text()); shutil.copytree(manifest['model_bundle'], '/opt/isr/model')"

FROM python:3.12-slim
COPY --from=builder /usr/local /usr/local
COPY --from=builder /opt/isr/model /opt/isr/model
RUN useradd --uid 10001 --create-home isr && mkdir /var/lib/isr && chown isr:isr /var/lib/isr
USER 10001
WORKDIR /home/isr
ENV ISR_MODEL_BUNDLE=/opt/isr/model ISR_DATABASE=/var/lib/isr/alerts.sqlite3
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "src.service.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
