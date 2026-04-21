#!/usr/bin/env python3
"""
阿算常驻调度器 v6.0 — 资讯+研究+彩票合并为一封邮件
v6.0改动：
1. 🔴 合并daily-news和daily-research为daily-digest，一封邮件搞定
2. 🟢 一次API调用生成全部内容（资讯+研究+彩票），避免多封邮件问题
3. 🟢 继承v5.0: SQLite持久化 + daemon.sh守护 + 占位文本防护
"""

import time
import os
import sys
import logging
import smtplib
import glob
import markdown
import json
import hashlib
import sqlite3
import requests
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# 彩票分析模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lottery_analyzer import generate_lottery_recommendations

CST = timezone(timedelta(hours=8))

PID_FILE = os.environ.get('PID_FILE', '/workspace/ai-memory/cron-scripts/scheduler.pid')
STATE_DB = os.environ.get('STATE_DB', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state.db'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# 邮件配置 — 🔴 优先环境变量，回退硬编码（sandbox兼容）
SMTP_SERVER = 'smtp.163.com'
SMTP_PORT = 465
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASSWORD', '')
SMTP_TO = os.environ.get('SMTP_TO', '')

# API配置 — 🔴 优先环境变量，回退硬编码
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
DASHSCOPE_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

# API配置 — 办公室qwopus3.5（免费，不限量）
OFFICE_API_BASE = os.environ.get('OFFICE_API_BASE', '')
OFFICE_API_KEY = os.environ.get('OFFICE_API_KEY', '')
OFFICE_MODEL = 'qwopus3.5-27b-v3.5'
OFFICE_ENABLED = False  # ⏸️ qwopus3.5还不稳定，等朋友确认后再开

_BASE_DIR = os.environ.get('BASE_DIR', os.path.dirname(os.path.abspath(__file__)))

TASKS = {
    'daily-digest': {
        'hour': 0, 'minute': 0,
        'output_dir': os.environ.get('OUTPUT_DIR', os.path.join(_BASE_DIR, 'output')),
        'desc': '阿算日报',
        'email_subject_prefix': '阿算日报',
        'model': 'deepseek-r1',  # 合并后用R1，质量更好
        'use_office': True,
        'system_prompt': os.environ.get('SYSTEM_PROMPT', '你是阿算，一个投资分析AI助手。请生成每日综合报告，重点关注AI算力和出海方向。'),
        'system_prompt_office': os.environ.get('SYSTEM_PROMPT_OFFICE', '你是阿算，一个投资分析AI助手。请为一人公司创业者生成每日综合报告，重点关注AI算力和出海方向。'),  # 脱敏版
        'user_prompt_template': '''请生成{date}的每日综合报告，包含以下四大部分：

## 一、每日资讯
每个领域2-3条，格式为markdown：
1. **时事新闻**：国内外重大新闻
2. **科技/AI资讯**：AI、编程、互联网动态
3. **财经/投资资讯**：A股、港股、美股市场动态
4. **热搜话题**：微博/抖音热门

## 二、市场扫描（投资创业研究）
分析以下方向的重要动态（每个2-3条）：
1. 英伟达算力市场供需和价格变动
2. 🔴 算力掮客动态：国内算力出海、海外剩余算力引入、GPU转租/分销
3. 🔴 台湾-大陆GPU算力转租：台湾不受出口管制，借台湾身份做GPU采购/转租中介
4. 🔴 矿场转型算力：原比特币矿场的闲置GPU+低价电力，转AI推理的资源和渠道
5. 🔴 OPC注册政策：普陀区及周边区一人公司优惠对比、算力补贴、返税比例
6. AI伴侣/AI硬件产品新品牌和新品发布
7. 一人公司/solopreneur成功案例

## 三、新闻后果推演（不可跳过！）
选至少2条最重要的新闻/动态，按5层传导法推演：
- 第1层：直接影响什么产业/公司
- 第2层：供应链传导
- 第3层：替代效应
- 第4层：二阶效应
- 判断：可预判/黑天鹅 | 时间窗口

## 四、投资机会与创业项目
### A. 投资机会
分析A股/港股以下方向的机会：
1. 算力产业链 2. AI硬件 3. 贵金属/期货 4. 出海概念股

### B. 创业项目筛选
优先从以下方向推荐1个高落地性项目：
- 🔴 台湾-大陆GPU算力转租中介：轻资产一人公司，借太太台湾人身份
- 🔴 算力掮客：连接国内外算力供需+矿场转型闲置GPU对接AI需求方
- 🔴 OPC注册：普陀区及周边区政策对比，选最优注册地
- AI推理服务/API代理
- AI硬件出海（借台湾人优势）

必须包含：具体做什么 / 需要多少钱、多长时间 / 第一步干什么 / 预期收益 / 风险和退出方式

最后给3-5条具体行动建议。

注意：你无法搜索互联网，请基于你的知识给出合理分析。如果无法获取当日最新数据，请明确标注"基于近期趋势分析"。''',
        'user_prompt_template_office': '''请生成{date}的每日综合报告，包含以下四大部分：

## 一、每日资讯
每个领域2-3条：
1. **时事新闻**：国内外重大新闻
2. **科技/AI资讯**：AI、编程、互联网动态
3. **财经/投资资讯**：A股、港股、美股市场动态
4. **热搜话题**：微博/抖音热门

## 二、市场扫描（投资创业研究）
分析以下方向的重要动态（每个2-3条）：
1. 英伟达算力市场供需和价格变动
2. 算力租赁和转租市场动态
3. 跨境GPU算力中介：不受出口管制地区的GPU资源对接国内需求
4. 比特币矿场转型AI算力：闲置GPU+低价电力的转型机会
5. AI硬件产品新品发布
6. 一人公司/solopreneur成功案例

## 三、新闻后果推演（不可跳过！）
选至少2条最重要的动态，按5层传导法推演：
- 第1层→第2层→第3层→第4层→判断

## 四、投资机会与创业项目
### A. 投资机会
1. 算力产业链 2. AI硬件 3. 贵金属/期货 4. 出海概念股

### B. 创业项目
推荐1个高落地性项目，包含：具体做什么/需要多少钱/第一步干什么/预期收益/风险和退出方式

最后给3-5条具体行动建议。

注意：你无法搜索互联网，请基于你的知识给出合理分析。''',  # 脱敏版
    }
}


# ============================================================
# 🟢 SQLite state.db — 持久化状态管理
# ============================================================

def init_db():
    """初始化SQLite数据库"""
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    # 已执行任务记录（替代内存中的 executed_today）
    c.execute('''CREATE TABLE IF NOT EXISTS executed_tasks (
        date TEXT NOT NULL,
        task_name TEXT NOT NULL,
        success INTEGER NOT NULL DEFAULT 1,
        executed_at TEXT NOT NULL,
        PRIMARY KEY (date, task_name)
    )''')
    # 邮件发送记录（替代 sent-log.json）
    c.execute('''CREATE TABLE IF NOT EXISTS sent_log (
        task_name TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        sent_at TEXT NOT NULL,
        PRIMARY KEY (task_name, content_hash)
    )''')
    # 调度器心跳（用于检测沙箱休眠/恢复）
    c.execute('''CREATE TABLE IF NOT EXISTS heartbeat (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        last_tick TEXT NOT NULL,
        pid INTEGER NOT NULL
    )''')
    # 启动记录（用于追踪沙箱恢复次数）
    c.execute('''CREATE TABLE IF NOT EXISTS startup_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        pid INTEGER NOT NULL,
        recovered_tasks TEXT DEFAULT ''
    )''')
    conn.commit()
    conn.close()
    logging.info(f"[DB] state.db 初始化完成: {STATE_DB}")


def db_exec(query, params=(), fetch=False):
    """SQLite执行辅助函数"""
    conn = sqlite3.connect(STATE_DB)
    try:
        c = conn.cursor()
        c.execute(query, params)
        conn.commit()
        if fetch:
            return c.fetchall()
        return None
    finally:
        conn.close()


def is_task_executed(date_str, task_name):
    """检查某日某任务是否已执行"""
    rows = db_exec(
        "SELECT success FROM executed_tasks WHERE date=? AND task_name=?",
        (date_str, task_name), fetch=True
    )
    return bool(rows and rows[0][0])


def mark_task_executed(date_str, task_name, success=True):
    """记录某日某任务已执行"""
    now_str = datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')
    db_exec(
        "INSERT OR REPLACE INTO executed_tasks (date, task_name, success, executed_at) VALUES (?, ?, ?, ?)",
        (date_str, task_name, 1 if success else 0, now_str)
    )


def clear_old_executed_tasks(keep_days=3):
    """清理旧的任务执行记录，只保留最近N天"""
    from datetime import timedelta
    cutoff = (datetime.now(CST) - timedelta(days=keep_days)).strftime('%Y-%m-%d')
    db_exec("DELETE FROM executed_tasks WHERE date < ?", (cutoff,))


# 邮件发送记录（迁移自 sent-log.json）
def is_already_sent(task_name, file_path):
    try:
        with open(file_path, 'rb') as f:
            content_hash = hashlib.md5(f.read()).hexdigest()
    except Exception:
        return False
    rows = db_exec(
        "SELECT 1 FROM sent_log WHERE task_name=? AND content_hash=?",
        (task_name, content_hash), fetch=True
    )
    return bool(rows)


def mark_as_sent(task_name, file_path):
    try:
        with open(file_path, 'rb') as f:
            content_hash = hashlib.md5(f.read()).hexdigest()
    except Exception:
        return
    now_str = datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')
    db_exec(
        "INSERT OR REPLACE INTO sent_log (task_name, content_hash, sent_at) VALUES (?, ?, ?)",
        (task_name, content_hash, now_str)
    )
    # 清理旧记录（保留最近50条）
    db_exec("""
        DELETE FROM sent_log WHERE rowid NOT IN (
            SELECT rowid FROM sent_log ORDER BY sent_at DESC LIMIT 50
        )
    """)


# 心跳检测
def update_heartbeat(pid):
    now_str = datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')
    db_exec(
        "INSERT OR REPLACE INTO heartbeat (id, last_tick, pid) VALUES (1, ?, ?)",
        (now_str, pid)
    )


def log_startup(pid, recovered_tasks=''):
    now_str = datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')
    db_exec(
        "INSERT INTO startup_log (started_at, pid, recovered_tasks) VALUES (?, ?, ?)",
        (now_str, pid, recovered_tasks)
    )


def get_last_heartbeat():
    rows = db_exec("SELECT last_tick, pid FROM heartbeat WHERE id=1", fetch=True)
    if rows:
        return rows[0]
    return None, None


# ============================================================
# 原有功能函数
# ============================================================

def send_email(subject, body_html):
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = SMTP_TO or SMTP_USER
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, SMTP_TO or SMTP_USER, msg.as_string())
        server.quit()
        logging.info(f"[邮件] 发送成功: {subject}")
        return True
    except Exception as e:
        logging.error(f"[邮件] 发送失败: {e}")
        return False


def find_today_file(output_dir, today_str):
    pattern = os.path.join(output_dir, f"{today_str}*.md")
    files = glob.glob(pattern)
    if files:
        return max(files, key=os.path.getmtime)
    return None


def generate_with_deepseek(task_name, task, today_str):
    """用API生成研究内容 — 优先办公室Qwen3.6（免费），失败回退百炼DeepSeek"""
    model = task.get('model', 'deepseek-v3')
    user_prompt = task['user_prompt_template'].format(date=today_str)
    system_prompt = task['system_prompt']

    # 优先使用办公室Qwen3.6（免费不限量）
    # 走办公室API时自动切换到脱敏版prompt，防止第三方服务器看到敏感信息
    use_office = task.get('use_office', True)

    if use_office and OFFICE_ENABLED:
        logging.info(f"[{task_name}] 尝试办公室qwopus3.5（脱敏模式）...")
        office_system = task.get('system_prompt_office', system_prompt)
        office_prompt_template = task.get('user_prompt_template_office', task['user_prompt_template'])
        office_user_prompt = office_prompt_template.format(date=today_str)

        result = _call_api(
            task_name=task_name,
            base_url=OFFICE_API_BASE,
            api_key=OFFICE_API_KEY,
            model=OFFICE_MODEL,
            system_prompt=office_system,
            user_prompt=office_user_prompt,
            max_tokens=8000,
            timeout=180,  # 🔴 办公室Qwen3.6约5-8 tokens/sec，3分钟够生成2000+tokens
        )
        if result:
            return result
        logging.warning(f"[{task_name}] 办公室Qwen3.6超时或失败，回退百炼DeepSeek（完整prompt）")

    # 回退到百炼DeepSeek — 使用完整版prompt（HTTPS加密传输，安全）
    logging.info(f"[{task_name}] 使用百炼DeepSeek: model={model}")
    return _call_api(
        task_name=task_name,
        base_url=DASHSCOPE_BASE_URL,
        api_key=DASHSCOPE_API_KEY,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=8000,
        timeout=300,
    )


def _call_api(task_name, base_url, api_key, model, system_prompt, user_prompt, max_tokens=8000, timeout=300):
    """通用API调用函数"""
    logging.info(f"[{task_name}] API调用: {base_url} model={model}")

    try:
        resp = requests.post(
            f'{base_url}/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                'max_tokens': max_tokens,
                'temperature': 0.7
            },
            timeout=timeout
        )
        data = resp.json()

        if 'choices' not in data:
            error_msg = json.dumps(data, ensure_ascii=False)[:200]
            logging.error(f"[{task_name}] API调用失败: {error_msg}")
            return None

        content = data['choices'][0]['message']['content']
        usage = data.get('usage', {})
        reasoning = data.get('completion_tokens_details', {}).get('reasoning_tokens', 0)

        # 🔴 过滤R1的think标签（避免推理过程混入邮件内容）
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

        # Qwen3.6的reasoning在message.reasoning字段
        msg = data['choices'][0]['message']
        if not reasoning and msg.get('reasoning'):
            reasoning = len(msg['reasoning'].split())

        logging.info(f"[{task_name}] 生成完成: tokens={usage.get('total_tokens','?')}, reasoning≈{reasoning}")

        if not content or len(content.strip()) < 50:
            logging.error(f"[{task_name}] 内容为空或过短({len(content)}字符)")
            return None

        return content

    except requests.exceptions.Timeout:
        logging.error(f"[{task_name}] API超时({timeout}秒)")
        return None
    except Exception as e:
        logging.error(f"[{task_name}] API调用异常: {e}")
        return None


def send_task_email(task, today_str, file_path, subject_override=None):
    """读取文件并发送邮件（🔴 彩票内容已在写文件时写入，直接读文件发送即可）"""
    task_name = task.get('name', '')
    if is_already_sent(task_name, file_path):
        logging.info(f"[邮件] 已发送过，跳过: {file_path}")
        return False

    try:
        with open(file_path, 'r') as f:
            content = f.read()
    except Exception as e:
        logging.error(f"[邮件] 读取文件失败: {e}")
        return False

    if not content or len(content.strip()) < 50:
        logging.error(f"[邮件] 文件内容为空或过短({len(content)}字符)，不发空邮件！")
        return False

    if '详见Gitee仓库' in content and len(content) < 100:
        logging.error(f"[邮件] 内容为占位文本，不发空邮件！")
        return False

    subject = subject_override or f"{task['email_subject_prefix']} | {today_str} | {task['desc']}"

    # 🔴 将markdown转成HTML，确保邮件正常渲染（163邮箱对pre-wrap+长文本渲染差）
    html_content = markdown.markdown(content, extensions=['tables', 'fenced_code', 'nl2br'])

    body = f"""<html><head><meta charset="utf-8">
<style>
body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; font-size: 14px; line-height: 1.7; color: #333; max-width: 800px; margin: 0 auto; padding: 10px; }}
h1 {{ font-size: 20px; border-bottom: 2px solid #e74c3c; padding-bottom: 6px; }}
h2 {{ font-size: 17px; color: #2c3e50; margin-top: 20px; border-left: 4px solid #3498db; padding-left: 10px; }}
h3 {{ font-size: 15px; color: #555; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: center; }}
th {{ background: #f5f5f5; }}
blockquote {{ border-left: 3px solid #e74c3c; padding-left: 10px; color: #666; margin: 10px 0; }}
code {{ background: #f4f4f4; padding: 1px 4px; border-radius: 3px; }}
hr {{ border: none; border-top: 1px solid #ddd; margin: 20px 0; }}
</style>
</head><body>
{html_content}
<hr>
<p style="color:#999;font-size:12px;">— 阿算 | 刘海蟾点金 | {datetime.now(CST).strftime('%H:%M')}</p>
</body></html>"""

    success = send_email(subject, body)
    if success:
        mark_as_sent(task_name, file_path)
    return success


def run_task_and_email(task_name, task, today_str):
    """生成内容 + 写文件 + 发邮件"""
    task['name'] = task_name

    # 🟢 检查DB中是否已执行（防止沙箱恢复后重复生成，浪费token）
    if is_task_executed(today_str, task_name):
        logging.info(f"[{task_name}] DB记录显示今日已执行，跳过")
        return True

    # 第一步：生成内容
    content = generate_with_deepseek(task_name, task, today_str)

    # 🔴 防护：如果API返回占位文本，重试一次
    if content and ('详见Gitee仓库' in content or '已完成，详见' in content or '详见仓库' in content):
        logging.warning(f"[{task_name}] API返回了占位文本，5秒后重试...")
        time.sleep(5)
        content = generate_with_deepseek(task_name, task, today_str)
        if content and ('详见Gitee仓库' in content or '已完成，详见' in content or '详见仓库' in content):
            logging.error(f"[{task_name}] 重试后仍返回占位文本，放弃")
            content = None

    # 🔴 第二步：生成彩票推荐（刘海蟾点金）
    lottery_section = ''
    try:
        logging.info("[彩票] 开始生成推荐...")
        lottery_section = generate_lottery_recommendations()
        logging.info(f"[彩票] 推荐生成完成: {len(lottery_section)}字符")
    except Exception as e:
        logging.error(f"[彩票] 推荐生成失败: {e}")
        lottery_section = '\n---\n🎰 彩票推荐生成异常，请手动运行lottery_analyzer.py\n---\n'

    # 第三步：写入文件（🔴 含彩票内容，保证文件和邮件一致）
    output_file = None
    if content:
        title = '阿算日报'
        full_content = f"# {title} — {today_str}\n\n---\n\n{content}{lottery_section}"

        os.makedirs(task['output_dir'], exist_ok=True)
        file_path = os.path.join(task['output_dir'], f"{today_str}.md")
        with open(file_path, 'w') as f:
            f.write(full_content)

        logging.info(f"[{task_name}] 文件已写入: {file_path} ({len(full_content)}字符)")

        if '推演' not in full_content:
            logging.warning(f"[{task_name}] ⚠️ 内容缺少'推演'关键词，可能不完整")

        output_file = file_path

    # 第四步：发送邮件
    # 🔴 GitHub Actions默认发邮件（主力），sandbox默认不发（SEND_EMAIL控制）
    no_email = os.environ.get('NO_EMAIL', '').lower() in ('1', 'true', 'yes')
    send_email_flag = os.environ.get('SEND_EMAIL', '').lower() in ('1', 'true', 'yes')
    # 默认行为：如果没设任何标志，GitHub Actions环境发邮件，sandbox不发
    run_env = os.environ.get('RUN_ENV', '')
    should_send = send_email_flag or (not no_email and run_env != 'sandbox')
    if not should_send:
        logging.info(f"[{task_name}] 跳过邮件发送（GitHub Actions主力发邮件）")
    elif output_file:
        send_task_email(task, today_str, output_file)
    else:
        # 生成失败，找最近的文件
        pattern = os.path.join(task['output_dir'], "*.md")
        files = glob.glob(pattern)
        if files:
            recent = max(files, key=os.path.getmtime)
            if not is_already_sent(task_name, recent):
                subject = f"{task['email_subject_prefix']} | {today_str} | {task['desc']}（使用近期数据）"
                send_task_email(task, today_str, recent, subject_override=subject)
        else:
            subject = f"{task['email_subject_prefix']} | {today_str} | {task['desc']}（生成异常）"
            body = f"""<p>{task['desc']}生成异常，请手动检查。</p>
            <p>时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p>"""
            send_email(subject, body)

    # 🟢 记录执行状态到DB
    success = output_file is not None
    mark_task_executed(today_str, task_name, success)
    return success


def write_pid():
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))


def cleanup_pid():
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


# ============================================================
# 🟢 迁移旧数据 sent-log.json → state.db
# ============================================================

def migrate_sent_log():
    """将旧的 sent-log.json 迁移到 SQLite"""
    old_log = '/workspace/ai-memory/cron-scripts/sent-log.json'
    if not os.path.exists(old_log):
        return
    try:
        with open(old_log, 'r') as f:
            old_data = json.load(f)
        if not old_data:
            return
        conn = sqlite3.connect(STATE_DB)
        c = conn.cursor()
        for key, sent_at in old_data.items():
            # key格式: "daily-news-md5hash" 或 "daily-research-md5hash"
            # 用 rsplit 从右边拆，因为task_name可能含连字符
            parts = key.rsplit('-', 1)
            if len(parts) == 2:
                task_name, content_hash = parts
                c.execute(
                    "INSERT OR IGNORE INTO sent_log (task_name, content_hash, sent_at) VALUES (?, ?, ?)",
                    (task_name, content_hash, sent_at)
                )
        conn.commit()
        conn.close()
        # 迁移完成后重命名旧文件
        os.rename(old_log, old_log + '.migrated')
        logging.info(f"[迁移] sent-log.json → state.db 完成，旧文件已重命名为 .migrated")
    except Exception as e:
        logging.error(f"[迁移] sent-log.json 迁移失败: {e}")


# ============================================================
# 主函数
# ============================================================

def main():
    # 初始化DB
    init_db()
    migrate_sent_log()

    # 记录启动
    last_tick, last_pid = get_last_heartbeat()
    pid = os.getpid()

    # 检测是否从沙箱休眠中恢复
    recovered = []
    if last_tick:
        try:
            last_time = datetime.strptime(last_tick, '%Y-%m-%d %H:%M:%S')
            gap = (datetime.now(CST) - last_time.replace(tzinfo=None)).total_seconds()
            if gap > 600:  # 心跳中断超过10分钟，判定为沙箱休眠恢复
                logging.info(f"🔴 检测到沙箱休眠恢复！上次心跳: {last_tick}，间隔: {gap:.0f}秒")
        except:
            pass

    log_startup(pid)

    logging.info("=" * 50)
    logging.info(f"阿算常驻调度器v6.0启动 — 合并日报+研究为一封邮件 + SQLite持久化")
    logging.info(f"PID: {pid}")
    logging.info(f"注册任务: {list(TASKS.keys())}")
    logging.info(f"上次心跳: {last_tick or '无'} (PID: {last_pid or '无'})")

    write_pid()

    now = datetime.now(CST)
    today = now.strftime('%Y-%m-%d')

    # 启动时检查未发送的文件
    for task_name, task in TASKS.items():
        task['name'] = task_name
        existing = find_today_file(task['output_dir'], today)
        if existing:
            if not is_already_sent(task_name, existing):
                logging.info(f"[{task_name}] 发现今日文件未发送: {existing}，补发邮件")
                send_task_email(task, today_str=today, file_path=existing)
                mark_task_executed(today, task_name)
            else:
                logging.info(f"[{task_name}] 今日文件已发送过: {existing}")

    # 补执行错过的任务（🟢 从DB读取状态，而非内存dict）
    for task_name, task in TASKS.items():
        task['name'] = task_name
        if not is_task_executed(today, task_name):
            if now.hour > task['hour'] or (now.hour == task['hour'] and now.minute > task['minute']):
                logging.info(f"[{task_name}] 检测到错过的任务，补执行: {task['desc']}")
                recovered.append(task_name)
                run_task_and_email(task_name, task, today)

    # 记录恢复的任务
    if recovered:
        log_startup(pid, ','.join(recovered))

    # 清理旧的执行记录
    clear_old_executed_tasks(keep_days=3)

    last_date = today

    while True:
        try:
            now = datetime.now(CST)
            today = now.strftime('%Y-%m-%d')

            # 新的一天
            if today != last_date:
                logging.info(f"新的一天: {today}")
                last_date = today
                clear_old_executed_tasks(keep_days=3)

            # 检查并执行到点任务
            for task_name, task in TASKS.items():
                task['name'] = task_name
                if not is_task_executed(today, task_name):
                    if now.hour == task['hour'] and now.minute == task['minute']:
                        run_task_and_email(task_name, task, today)

            # 🟢 更新心跳
            update_heartbeat(pid)

            time.sleep(60)
        except KeyboardInterrupt:
            logging.info("调度器被手动停止")
            break
        except Exception as e:
            logging.error(f"🔴 主循环异常: {e}", exc_info=True)
            logging.info("等待60秒后恢复...")
            time.sleep(60)

    cleanup_pid()
    logging.info("调度器退出")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Run once and exit (for GitHub Actions)')
    args = parser.parse_args()

    if args.once:
        # 🔴 单次执行模式（GitHub Actions / 手动调试）
        init_db()
        now = datetime.now(CST)
        today = now.strftime('%Y-%m-%d')
        logging.info(f"单次执行模式: {today}")
        for task_name, task in TASKS.items():
            task['name'] = task_name
            if not is_task_executed(today, task_name):
                run_task_and_email(task_name, task, today)
            else:
                logging.info(f"[{task_name}] 今日已执行，跳过")
    else:
        main()
