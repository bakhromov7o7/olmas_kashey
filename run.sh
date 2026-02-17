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
        echo "Bot to'xtatilyapti (PID: $PID)..."
        kill $PID 2>/dev/null
        rm "$PID_FILE"
    fi
    # Backup: Kill any remaining olmas_kashey processes
    pkill -f "$APP_NAME" 2>/dev/null
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
    *)
        echo "Foydalanish: $0 {start|stop|status|logs}"
        exit 1
esac
