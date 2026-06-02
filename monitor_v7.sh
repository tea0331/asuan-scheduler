#!/bin/bash
# V7日报监控脚本 - 每天07:35运行
# 检查07:30任务是否成功，失败则告警

LOG_FILE="/tmp/generate_full.log"
NOW=$(date)
TODAY=$(date +%Y-%m-%d)

# 检查今日是否有ERROR
ERROR_COUNT=$(grep "$TODAY" $LOG_FILE 2>/dev/null | grep -c "ERROR\|Traceback\|失败" || echo "0")

if [ "$ERROR_COUNT" -gt "0" ]; then
    echo "[$NOW] V7监控: 发现$ERROR_COUNT个错误，请检查$LOG_FILE"
else
    echo "[$NOW] V7监控: 运行正常，无错误"
fi

# 检查今日邮件是否发送成功
SMTP_LOG=$(grep "$TODAY.*邮件发送成功" $LOG_FILE 2>/dev/null | tail -1)
if [ -n "$SMTP_LOG" ]; then
    echo "[$NOW] V7监控: 邮件发送成功"
else
    echo "[$NOW] V7监控: 邮件发送失败！请检查$LOG_FILE"
fi
