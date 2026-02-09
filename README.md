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
# Olmas Kashey 🚀

AI-powered Telegram group discovery and automation tool.

## 🛠 O'rnatish va Sozlash (Setup)

Do'stingiz yoki boshqa foydalanuvchilar loyihani ishlatishi uchun quyidagi bosqichlarni bajarishlari kerak:

### 1. Python va Loyihani ko'chirib olish
- Kompyuterda Python 3.9+ o'rnatilgan bo'lishi kerak.
- Loyihani clone qiling:
  ```bash
  git clone https://github.com/bakhromov7o7/olmas_kashey.git
  cd olmas_kashey
  ```

### 2. Virtual Muhit va Kutubxonalar
Virtual muhit yarating va kerakli kutubxonalarni o'rnating:
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### 3. Konfiguratsiya (.env)
`.env.example` faylini `.env` deb nusxalang va ichini to'ldiring:
```bash
cp .env.example .env
```
Fayl ichida quyidagilar bo'lishi shart:
- `TELEGRAM__API_ID` & `TELEGRAM__API_HASH`: [my.telegram.org](https://my.telegram.org) manzilidan olinadi.
- `GROQ__API_KEY`: AI keyword generatsiyasi uchun [Groq Cloud](https://console.groq.com/) kaliti.

### 4. Ma'lumotlar bazasini ishga tushirish
Dasturni birinchi marta ishlatishdan oldin bazani yaratib oling:
```bash
python -m olmas_kashey init-db
```

## 🚀 Ishlatish (Usage)

### Continuous Search (AI-Powered)
AI orqali guruhlarni qidirish va avtomatik join bo'lish:
```bash
python -m olmas_kashey continuous-search --topic "ielts" --delay 10
```

### Xususiyatlari:
- **Robust Discovery**: Emojilar va xato yozilgan nomlarni ham fuzzy-matching orqali topadi.
- **AI Keywords**: Groq LLM yordamida har xil variatsiyadagi qidiruv so'zlarini yaratadi.
- **Auto-Join**: Topilgan guruhlarga avtomatik a'zo bo'ladi (confidence score yuqori bo'lsa).

---
**Muallif:** @Bakhromov7o7
