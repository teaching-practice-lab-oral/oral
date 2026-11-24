FROM python:3.11-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' ca-certificates)" ge 20250419+deb13u1 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
COPY requirements.txt .
# Bootstrap pip with a verified wheel: its vendored CA bundle needs its own update.
RUN python -m pip install --no-cache-dir \
        "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70" \
    && python -m pip install --no-cache-dir setuptools==84.2.1 -r requirements.txt \
    && python -m pip check
COPY --chown=app:app . .
USER app
CMD ["sh", "-c", "exec gunicorn app.main:app --worker-class uvicorn.workers.UvicornWorker --workers ${GUNICORN_WORKERS:-4} --bind 0.0.0.0:7682 --forwarded-allow-ips ${FORWARDED_ALLOW_IPS:-127.0.0.1} --timeout 120 --graceful-timeout 30 --keep-alive 5 --no-control-socket"]
