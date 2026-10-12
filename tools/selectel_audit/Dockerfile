FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.title="NetBox Sync Selectel audit"
LABEL org.opencontainers.image.source="https://github.com/CloseName/netbox-sync"
ARG VCS_REF=unknown
LABEL org.opencontainers.image.revision=$VCS_REF
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app
COPY --chmod=0755 tools/selectel_audit /app/selectel_audit
USER 65532:65532
ENTRYPOINT ["python", "-m", "selectel_audit"]
