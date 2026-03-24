#!/bin/bash

LOG_FILE="/var/log/ai_monitor.log"
CONTAINER_NAME="ollama"
API_URL="http://127.0.0.1:11434/api/generate"

sudo touch $LOG_FILE
sudo chmod 666 $LOG_FILE

echo "========== 健康检查启动于 $(date) ==========" >> $LOG_FILE

while true; do
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

    # 先确认容器在不在
    if ! docker ps --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
        echo "$TIMESTAMP ERROR: 容器 $CONTAINER_NAME 未运行" >> $LOG_FILE
        sleep 30
        continue
    fi

    # 发一个请求，看 API 有没有响应
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL" \
        -d '{"model": "qwen:0.5b", "prompt": "ping", "stream": false}' \
        -H "Content-Type: application/json")

    if [ "$HTTP_CODE" -eq 200 ]; then
        echo "$TIMESTAMP SUCCESS: API 正常 (200)" >> $LOG_FILE
    else
        echo "$TIMESTAMP ERROR: API 返回 $HTTP_CODE" >> $LOG_FILE
    fi

    # 记录资源占用
    MEM_USAGE=$(docker stats --no-stream --format "{{.MemUsage}}" "$CONTAINER_NAME" | awk '{print $1}')
    CPU_PERCENT=$(docker stats --no-stream --format "{{.CPUPerc}}" "$CONTAINER_NAME")
    echo "$TIMESTAMP INFO: CPU=$CPU_PERCENT MEM=$MEM_USAGE" >> $LOG_FILE

    sleep 30
done
