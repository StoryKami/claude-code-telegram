#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PIDFILE="$PROJECT_DIR/data/.bot.pid"

cd "$PROJECT_DIR"

stop_bot() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping bot (PID $PID)..."
            kill "$PID"
            for i in $(seq 1 10); do
                kill -0 "$PID" 2>/dev/null || break
                sleep 0.5
            done
            if kill -0 "$PID" 2>/dev/null; then
                echo "Force killing..."
                kill -9 "$PID"
            fi
            echo "Stopped."
        else
            echo "Stale PID file (process $PID not running)."
        fi
        rm -f "$PIDFILE"
    else
        echo "No PID file found. Checking for running bot..."
        PIDS=$(pgrep -f "src\.main" 2>/dev/null || true)
        if [ -n "$PIDS" ]; then
            echo "Killing existing bot processes: $PIDS"
            echo "$PIDS" | xargs kill 2>/dev/null || true
            sleep 1
        fi
    fi
}

start_bot() {
    mkdir -p "$PROJECT_DIR/data"
    echo "Starting bot..."
    unset CLAUDECODE 2>/dev/null || true
    nohup poetry run claude-telegram-bot > "$PROJECT_DIR/data/bot.log" 2>&1 &
    echo $! > "$PIDFILE"
    echo "Bot started (PID $!)."
    echo "Log: $PROJECT_DIR/data/bot.log"
}

case "${1:-restart}" in
    start)
        start_bot
        ;;
    stop)
        stop_bot
        ;;
    restart)
        stop_bot
        start_bot
        ;;
    *)
        echo "Usage: $0 {start|stop|restart}"
        exit 1
        ;;
esac
