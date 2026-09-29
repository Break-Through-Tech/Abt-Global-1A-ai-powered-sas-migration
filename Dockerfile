FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

ARG USERNAME=sasguard
ARG USER_UID=1000
ARG USER_GID=1000

RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} --create-home --shell /bin/bash ${USERNAME}

WORKDIR /workspace

COPY --chown=${USERNAME}:${USERNAME} . .
RUN python -m pip install --no-cache-dir uv==0.8.22 \
    && uv sync --locked --no-build-isolation --group build --extra dev --extra notebooks --no-install-project \
    && uv sync --locked --no-build-isolation --group build --extra dev --extra notebooks

USER ${USERNAME}

CMD ["bash"]
