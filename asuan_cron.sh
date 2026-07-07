#!/bin/bash
cd /root/asuan-scheduler
export $(cat .env | xargs)
/usr/bin/python3 generate_full_daily.py >> /tmp/daily_cron.log 2>&1

# 生成 JinZhu 策略分析数据（供圆桌角色参考）
/usr/bin/python3 jinzhu_analysis_generator.py >> /tmp/daily_cron.log 2>&1

# 多角色圆桌推演：替代东方朔评价 + 马斯克推演
TODAY=$(date +%Y-%m-%d)
/usr/bin/python3 multi_roundtable.py $TODAY >> /tmp/roundtable.log 2>&1
