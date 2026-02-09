
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install poetry or pip requirements
COPY pyproject.toml .
# If we had poetry.lock we'd copy it too. Assuming standard pip install for now based on pyproject content not being poetry-specific yet?
# Wait, pyproject.toml implies poetry or hatch or standard.
# The user prompt showed basic pyproject.toml.
# Let's assume we install via pip from . or requirements.
# We haven't been maintaining requirements.txt. 
# We should probably install dependencies manually or via pip install . if setup.py exists?
# Or just list them here for now as we don't have a lock file strategy defined.
# The project has: telethon, sqlalchemy[asyncio], alembic, pydantic-settings, loguru, aiosqlite, typer, asyncpg (for postgres).
# Let's install them directly.

RUN pip install --no-cache-dir \
    telethon \
    "sqlalchemy[asyncio]" \
    alembic \
    pydantic-settings \
    loguru \
    aiosqlite \
    typer \
    asyncpg

COPY . .

# Environment variables should be passed at runtime
# CMD ["python", "-m", "olmas_kashey.cli.main", "start"]
ENTRYPOINT ["python", "-m", "olmas_kashey.cli.main"]
CMD ["start"]
