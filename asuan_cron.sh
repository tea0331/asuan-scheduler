#!/bin/bash
cd /root/asuan-scheduler
export $(cat .env | xargs)
/usr/bin/python3 generate_full_daily.py >> /tmp/daily_cron.log 2>&1

# 生成 JinZhu 策略分析数据（供东方朔⑤逆向回测维度使用）
/usr/bin/python3 jinzhu_analysis_generator.py >> /tmp/daily_cron.log 2>&1

# 东方朔：生成邪修评价并追加到日报末尾
TODAY=$(date +%Y-%m-%d)
/usr/bin/python3 evil_reviewer.py $TODAY >> /tmp/daily_cron.log 2>&1
