#!/usr/bin/env python3
"""step3_assemble.py — v8.6 分步执行: 拼装完整日报 + 发邮件

用法: python3 step3_assemble.py
依赖: cache/{date}_ai.md (step2 产出)
输出: output/{date}.md + 邮件发送

被杀后重跑: 直接重跑即可，邮件会重新发送
"""
import os
import sys
import logging

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from generate_full_daily import (
    today_str, output_dir, SMTP_PASS,
    generate_lottery_section, generate_taiwan_section, send_email,
)

CACHE_DIR = os.path.join(PROJECT_DIR, 'cache')
AI_PATH = os.path.join(CACHE_DIR, f'{today_str}_ai.md')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


def main():
    if not os.path.exists(AI_PATH):
        logging.error(f"[step3] 找不到 {AI_PATH}，请先运行 step2_generate.py")
        print(f"❌ step3 失败: 缺少依赖 {AI_PATH}")
        sys.exit(1)

    logging.info(f"========== step3 拼装+发送 {today_str} ==========")

    # 1. 读取 AI 生成的6板块
    with open(AI_PATH, 'r', encoding='utf-8') as f:
        news_content = f.read()
    logging.info(f"[step3] 读取AI内容: {len(news_content)}字符")

    # 2. 生成彩票部分
    try:
        lottery_content = generate_lottery_section()
    except Exception as e:
        logging.error(f"[step3] 彩票生成异常: {e}")
        lottery_content = "## 🎰 彩票推荐\n（今日彩票生成异常，下次自动恢复）\n"

    # 3. 生成台湾彩种
    try:
        taiwan_content = generate_taiwan_section()
    except Exception as e:
        logging.warning(f"[step3] 台湾彩种异常: {e}")
        taiwan_content = ""

    # 4. 拼接完整日报
    full_content = f"# 阿算帮刘老板发财日报 — {today_str}\n\n---\n\n{news_content}{lottery_content}{taiwan_content}"

    # 5. 质量守护
    try:
        from daily_report_guard import validate_report
        guard_result = validate_report(full_content)
        if guard_result['valid']:
            logging.info(f"[step3] ✅ 日报质量通过 (得分: {guard_result['score']}/100)")
        else:
            logging.warning(f"[step3] ⚠️ 日报质量问题: {guard_result['errors']}")
    except Exception as e:
        logging.warning(f"[step3] 守护验证异常(不阻塞): {e}")

    # 6. 写文件
    output_path = os.path.join(output_dir, f"{today_str}.md")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        logging.info(f"[step3] ✅ 已写入: {output_path} ({len(full_content)}字符)")
    except Exception as e:
        logging.error(f"[step3] 写入失败: {e}")
        fallback_path = f"/tmp/daily-report-{today_str}.md"
        with open(fallback_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        logging.info(f"[step3] 兜底写入: {fallback_path}")

    # 7. 发邮件
    if not SMTP_PASS:
        logging.warning("[step3] SMTP密码未配置，跳过邮件发送")
    else:
        try:
            subject = '阿算帮刘老板发财日报 | ' + today_str
            send_email(subject, full_content)
            logging.info(f"[step3] ✅ 邮件已发送")
        except Exception as e:
            logging.error(f"[step3] 邮件发送异常: {e}")

    print(f"✅ step3 完成: {output_path} ({len(full_content)}字符)")


if __name__ == '__main__':
    main()
