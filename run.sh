#!/bin/bash

# Configuration
APP_NAME="olmas_kashey"
LOG_FILE="bot.log"
PID_FILE="bot.pid"
VENV_PYTHON="./.venv/bin/python"

start() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "Bot allaqachon ishlayapti (PID: $(cat $PID_FILE))."
        return
    fi

    echo "Bot ishga tushirilyapti..."
    # Set PYTHONPATH so 'olmas_kashey' module is found in 'src' directory
    # Use 'start' command for full automation + control bot
    export PYTHONPATH=$PYTHONPATH:$(pwd)/src
    nohup $VENV_PYTHON -m $APP_NAME start > "$LOG_FILE" 2>&1 &
    
    PID=$!
    echo $PID > "$PID_FILE"
    echo "Bot fonda ishga tushdi. PID: $PID"
    echo "Loglarni ko'rish uchun: ./run.sh logs"
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        echo "Bot (PID: $PID) majburiy to'xtatilyapti..."
        kill -9 $PID 2>/dev/null
        rm "$PID_FILE"
    fi
    # Backup: Force Kill any remaining olmas_kashey processes
    pkill -9 -f "$APP_NAME" 2>/dev/null
    
    # Also aggressively kill anything holding the bot_session file if fuser is available
    if command -v fuser >/dev/null 2>&1; then
        fuser -k -9 bot_session.session* 2>/dev/null
    fi
    
    echo "Bot to'xtatildi."
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "Holat: Bot ishlayapti (PID: $(cat $PID_FILE))."
    else
        echo "Holat: Bot ishlamayapti."
    fi
}

logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f -n 100 "$LOG_FILE"
    else
        echo "Log fayli hali yaratilmagan."
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    init-db)
        export PYTHONPATH=$PYTHONPATH:$(pwd)/src
        $VENV_PYTHON -m $APP_NAME init-db
        ;;
    sync-groups)
        export PYTHONPATH=$PYTHONPATH:$(pwd)/src
        $VENV_PYTHON -m $APP_NAME sync-groups
        ;;
    monitor-joined)
        export PYTHONPATH=$PYTHONPATH:$(pwd)/src
        $VENV_PYTHON -m $APP_NAME run-monitor
        ;;
    setup)
        echo "Kutubxonalarni o'rnatyapman..."
        ./.venv/bin/pip install -e .
        ;;
    *)
        echo "Foydalanish: $0 {start|stop|status|logs|init-db}"
        exit 1
esac
