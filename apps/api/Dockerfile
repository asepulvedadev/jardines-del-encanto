FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72 AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.txt

FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build /install /usr/local
COPY app ./app
COPY migrations ./migrations
# Root-owned release extraction uses umask 077. COPY preserves private nested
# directory modes; make application code readable (not writable) by the runtime UID.
RUN chmod -R a=rX /app/app /app/migrations \
    && mkdir -p /var/lib/jardines-zernio \
    && chown 10001:10001 /var/lib/jardines-zernio \
    && chmod 700 /var/lib/jardines-zernio
USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
