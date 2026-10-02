FROM node:22-bookworm-slim AS frontend
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
# The frontend reads the product name from the Python package's brand file.
COPY waymark/brand.json /build/waymark/brand.json
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.0"
COPY pyproject.toml README.md ./
COPY waymark/ waymark/
COPY migrations/ migrations/
COPY alembic.ini ./
RUN pip install --no-cache-dir .
COPY --from=frontend /build/web/dist /app/web/dist
ENV APP_MODE=demo \
    DATA_DIR=/data \
    STATIC_DIR=/app/web/dist \
    EMAIL_TRANSPORT=preview \
    APP_BASE_URL=http://localhost:8000
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "waymark.api:app", "--host", "0.0.0.0", "--port", "8000"]
