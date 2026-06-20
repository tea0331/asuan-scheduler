#!/usr/bin/env python3
"""重新生成今日日报（带超时保护）"""
import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError

CST = timezone(timedelta(hours=8))
today_str = os.getenv('TODAY', datetime.now(CST).strftime('%Y-%m-%d'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 加载 .env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)

def main():
    logger.info(f"========== 重新生成日报 {today_str} ==========")
    
    # 1. 生成新闻板块（带超时）
    news_content = ""
    try:
        from generate_full_daily import generate_all_sections
        logger.info("[生成] 开始生成新闻板块...")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(generate_all_sections)
            news_content = future.result(timeout=200)
        logger.info(f"[生成] ✅ 新闻板块完成: {len(news_content)}字符")
    except TimeoutError:
        logger.error("[生成] 新闻板块超时")
        return False
    except Exception as e:
        logger.error(f"[生成] 新闻板块异常: {e}")
        return False
    
    # 2. 生成彩票板块
    lottery_content = ""
    try:
        from generate_full_daily import generate_lottery_section
        lottery_content = generate_lottery_section()
        logger.info(f"[生成] ✅ 彩票板块完成: {len(lottery_content)}字符")
    except Exception as e:
        logger.error(f"[生成] 彩票板块异常: {e}")
    
    # 3. 生成台湾板块
    taiwan_content = ""
    try:
        from generate_full_daily import generate_taiwan_section
        taiwan_content = generate_taiwan_section()
        logger.info(f"[生成] ✅ 台湾板块完成: {len(taiwan_content)}字符")
    except Exception as e:
        logger.error(f"[生成] 台湾板块异常: {e}")
    
    # 4. 拼接完整日报
    content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery_content}{taiwan_content}"
    
    # 5. 写文件
    output_path = os.path.join(OUTPUT_DIR, f"{today_str}.md")
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"[写入] ✅ {output_path} ({len(content)}字符)")
    except Exception as e:
        logger.error(f"[写入] 失败: {e}")
        return False
    
    # 6. 发邮件
    try:
        from resend_daily_with_evil import send_email
        subject = f'阿算帮刘老板发财日报 | {today_str}（含东方朔邪修评价）'
        send_email(subject, content)
        logger.info("[邮件] ✅ 发送成功")
    except Exception as e:
        logger.error(f"[邮件] 发送失败: {e}")
    
    logger.info(f"========== 完成 {today_str} ==========")
    return True

if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
