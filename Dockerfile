# okf-mcp-gateway: multi-owner Streamable HTTP MCP gateway.
#
# python-slim base + git (runtime clone/fetch of owner repos) + uv (dependency
# install from the frozen lock). The image installs the package and runs the
# okf-mcp-gateway console script. Build/run is a manual step (pulls base images
# and clones owner repos over the network); see README "Gateway".
FROM python:3.14-slim

# git is required at runtime: the gateway shallow-clones and fetches owner repos.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# uv from its official image; no pip/poetry (project policy).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    OKF_GATEWAY_CACHE_DIR=/var/cache/okf-mcp-gateway \
    OKF_GATEWAY_SERVERS=/app/servers.yaml \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

# Install dependencies first (cached until the lock changes), then the project.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# Private/corporate CA trust (extension point). PEM *.crt files dropped into
# certs/ (gitignored; empty by default) are installed into the system trust
# store, so the gateway can clone from git hosts behind a private CA (e.g.
# Bitbucket Data Center). Placed after the dependency layers so editing certs
# does not invalidate the uv sync cache. The find strips .gitkeep/README.md so
# only real CAs land in the trust dir; an empty certs/ is a no-op and the image
# is unchanged for public hosts.
COPY certs/ /usr/local/share/ca-certificates/okf-extra/
RUN find /usr/local/share/ca-certificates/okf-extra/ -type f ! -name '*.crt' -delete \
 && update-ca-certificates

# Run unprivileged; own /app and the checkout cache so the named volume (which
# inherits this mountpoint's ownership on first creation) stays writable.
RUN useradd --create-home --uid 10001 gateway \
 && mkdir -p /var/cache/okf-mcp-gateway \
 && chown -R gateway:gateway /app /var/cache/okf-mcp-gateway
USER gateway

EXPOSE 8080

CMD ["okf-mcp-gateway"]
