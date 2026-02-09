# Olmas Kashey

Olmas Kashey is a production-grade Telegram automation tool designed to discover and classify relevant public groups (specifically targeting IELTS and Uzbekistan topics). It is built with Python 3.12, Telethon, and SQLAlchemy.

## Features

- **Safe Automation**: Adheres to Telegram's ToS with strict rate limiting and flood-wait handling.
- **Discovery Service**: Search for public groups using keywords.
- **Classification**: Filter groups based on title and description (IELTS/Uzbekistan focus).
- **Persistence**: Store group data in a database (SQLite/PostgreSQL) using SQLAlchemy.
- **CLI**: Command-line interface for managing the automation.

## Requirements

- Python 3.12+
- Telegram API ID and Hash (from [my.telegram.org](https://my.telegram.org))

## Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/olmas-kashey.git
    cd olmas-kashey
    ```

2.  **Create a virtual environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install .
    # Or for development:
    pip install -e .[dev]
    ```

4.  **Configure Environment:**
    Copy `.env.example` to `.env` and fill in your API credentials.
    ```bash
    cp .env.example .env
    nano .env
    ```

## Usage

The application provides a CLI for interaction.

```bash
# Show help
python -m olmas_kashey.cli.main --help

# Initialize Database
python -m olmas_kashey.cli.main init-db

# Run Discovery Scan
python -m olmas_kashey.cli.main scan --keywords "ielts" --limit 10
```

## Development

- **Linting:** `ruff check .`
- **Type Checking:** `mypy .`
- **Testing:** `pytest`
# olmas_kashey
