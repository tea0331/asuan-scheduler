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
import re
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
SMTP_USER = os.environ.get('SMTP_USER', 'tea0331@163.com')
SMTP_PASS = os.environ.get('SMTP_PASSWORD', 'NYuLnGar8wT8RBit')
SMTP_TO = os.environ.get('SMTP_TO', 'tea0331@163.com')

# API配置 — 🔴 优先环境变量，回退硬编码
HUNYUAN_API_KEY = os.environ.get('HUNYUAN_API_KEY', 'sk-TjZgBJKZJA1FjrkMHIotwyBafg8gXnRdYBLDvyHNkGSkQAcq')
HUNYUAN_BASE_URL = 'https://api.hunyuan.cloud.tencent.com/v1'

# 百炼配置已废弃，统一使用混元

# API配置 — 办公室Qwen3.6-abliterated（免费，不限量，不会拒绝彩票预测）
OFFICE_API_BASE = os.environ.get('OFFICE_API_BASE', '')
OFFICE_API_KEY = os.environ.get('OFFICE_API_KEY', '')
OFFICE_MODEL = 'huihui-qwen3.6-27b-abliterated'
OFFICE_ENABLED = os.environ.get('OFFICE_ENABLED', 'true').lower() in ('true', '1', 'yes')  # 🟢 v6.5: 新模型更稳定，默认开启

_BASE_DIR = os.environ.get('BASE_DIR', os.path.dirname(os.path.abspath(__file__)))

TASKS = {
    'daily-digest': {
        'hour': 7, 'minute': 0,
        'output_dir': os.environ.get('OUTPUT_DIR', os.path.join(_BASE_DIR, 'output')),
        'desc': '阿算帮刘老板发财日报',
        'email_subject_prefix': '阿算帮刘老板发财日报',
        'model': 'deepseek-r1',  # 合并后用R1，质量更好
        'use_office': True,
        'system_prompt': os.environ.get('SYSTEM_PROMPT', '你是阿算，一个投资分析AI助手。请生成每日综合报告，重点关注AI算力和出海方向。'),
        'system_prompt_office': os.environ.get('SYSTEM_PROMPT_OFFICE', '你是阿算，一个投资分析AI助手。请为一人公司创业者生成每日综合报告，重点关注AI算力和出海方向。'),  # 脱敏版
        'user_prompt_template': '''请生成{date}的每日综合报告，包含以下四大部分：

## 一、每日资讯
每个领域2-3条，格式为markdown：
1. **时事新闻**：国内外重大新闻
2. **科技/AI资讯**：AI、编程、互联网动态
3. **商业/创业资讯**：新商业模式、创业案例、行业痛点、政策红利（不推股票行情，聚焦创业投资机会和缺口发现）
4. **热搜话题**：微博/抖音热门

## 二、市场缺口扫描（核心！天之道·损有余补不足）

🔴 **关键改变**：不再罗列固定方向的动态，而是主动发现**隐性需求缺口**——那些"有人需要但没人满足"的市场空间。

### 扫描方法：
1. **从痛点反推缺口**：找正在抱怨/焦虑/花冤枉钱的群体 → 他们的需求谁在满足？如果不充分=缺口
2. **从趋势找滞后**：技术/政策/人口趋势已变 → 配套服务/产品/基础设施是否跟上？没跟上=缺口
3. **从跨境/跨圈找信息差**：A地区/行业已成熟的做法 → B地区/行业是否还空白？空白=缺口
4. **从监管找合规真空**：新业态已出现 → 法规/资质/标准是否空白？空白=合规服务缺口

### 🔴 固定关注（不变）：
1. 英伟达算力市场供需和价格变动
2. 🔴 台湾-大陆GPU算力转租（台湾不受出口管制，借台湾身份做GPU采购/转租中介）
3. 🔴 OPC注册政策（普陀区及周边区一人公司优惠对比、算力补贴、返税比例）

### 🔴 动态缺口（每天必须不同！）：
从以下领域**主动发现**至少3个新的隐性需求缺口（不重复之前方向）：
- AI应用层：什么AI能力用户急需但工具难用/缺失？
- 消费升级/降级：什么消费需求正在分化但供给单一？
- 出海/跨境：什么国内经验可以复制到海外？什么海外模式可以引入？
- 银发/母婴/宠物：人口结构变化催生的服务缺口？
- 本地生活/社区：一线城市过剩但二三线空白的服务？
- 政策套利：新政策带来的合规/补贴/资质机会？
- 技术降维：高端技术可以做低端平替？谁需要但买不起？
- 文化/情绪价值：什么精神需求未被满足？玄学/祈福/疗愈/陪伴？

每个缺口必须包含：
- **缺口描述**：谁缺什么？为什么缺？
- **有余对照**：对应的"有余"在哪？（过剩的供给/过时的模式/过度的竞争）
- **补的方式**：怎么补？一人公司能做吗？需要多少钱？
- **时机判断**：现在补还是再等等？信号是什么？

## 三、新闻后果推演（不可跳过！）
选至少2条最重要的新闻/动态，按**纵向推演+横向定位**分析：

### A. 5层传导（纵向推演：这事会怎么演变）
- 第1层：直接影响什么产业/公司
- 第2层：供应链传导
- 第3层：替代效应
- 第4层：二阶效应
- 判断：可预判/黑天鹅 | 时间窗口

### B. 天之道定位（横向定位：现在站在哪里，该往哪走）
> 天之道，损有余而补不足。人之道，损不足以奉有余。市场短期走"人之道"（马太效应），长期走"天之道"（均值回归）。赚钱的本质：在天之道修正人之道的过程中，站在正确的一边。

对每条推演，必须用四步分析法：

1. **有余（被损方）**：供给过剩/估值过高/关注过度 → 被损（价格下跌、利润压缩、竞争内卷）
2. **不足（被补方）**：供给短缺/估值偏低/关注不足 → 被补（价格上涨、机会涌现、蓝海出现）
3. **再平衡方向**：市场将如何自发修正这个失衡？修正速度（快=政策触发/慢=自然周期）？修正阻力（既得利益者、路径依赖）？谁是赢家/输家？
4. **行动含义**：在再平衡完成前，该站在哪边？时机判断——是现在就站，还是等"人之道"走到极致再站？风险：再平衡可能比预期慢得多

## 四、逆潮观察（反直觉判断）
🟢 这是端木赐的核心价值——不做随大流的复读机，只给反直觉的独立判断。

从今天的资讯和市场中，找出2-3条"多数人这么想，但反过来才对"的判断：
- **多数人观点**：当前市场/舆论的主流看法
- **逆潮判断**：为什么多数人错了，真实方向是什么
- **逻辑支撑**：推演链条，不是拍脑袋
- **行动含义**：这个判断如果对了，现在该做什么

要求：
1. 必须真的反直觉，不能是"大家都觉得AI好，我也觉得AI好但要注意风险"这种假反直觉
2. 每条判断要有明确的可证伪条件（什么情况下判断失败）
3. 优先从以下角度找反直觉：资产定价错误、政策预期差、技术路线分歧、供需错配、情绪极端点

## 五、投资机会与创业项目
### A. 投资机会
分析A股/港股以下方向的机会：
1. 供需错配方向（有余vs不足） 2. 政策红利窗口 3. 技术降维机会 4. 跨境信息差套利

### B. 创业项目筛选
优先从**今天发现的缺口**中推荐1个最高落地性项目，不再限定固定方向。

必须包含：具体做什么 / 需要多少钱、多长时间 / 第一步干什么 / 预期收益 / 风险和退出方式

最后给3-5条具体行动建议。

注意：你无法搜索互联网，请基于你的知识给出合理分析。如果无法获取当日最新数据，请明确标注"基于近期趋势分析"。''',
        'user_prompt_template_office': '''请生成{date}的每日综合报告，包含以下四大部分：

## 一、每日资讯
每个领域2-3条：
1. **时事新闻**：国内外重大新闻
2. **科技/AI资讯**：AI、编程、互联网动态
3. **商业/创业资讯**：新商业模式、创业案例、行业痛点、政策红利（不推股票行情，聚焦创业投资机会和缺口发现）
4. **热搜话题**：微博/抖音热门

## 二、市场缺口扫描（天之道·损有余补不足）

主动发现**隐性需求缺口**——"有人需要但没人满足"的市场空间。

### 扫描方法：
1. **从痛点反推缺口**：抱怨/焦虑/花冤枉钱的群体 → 需求不满足=缺口
2. **从趋势找滞后**：技术/政策/人口已变 → 配套服务没跟上=缺口
3. **从跨境/跨圈找信息差**：A地区成熟做法 → B地区空白=缺口
4. **从监管找合规真空**：新业态出现 → 法规/资质空白=服务缺口

固定关注：算力供需、跨境GPU转租、OPC政策
动态缺口：每天从AI应用/消费分化/出海/银发母婴/本地生活/政策套利/技术降维/情绪价值等领域发现至少3个新缺口（不重复）

每个缺口包含：缺口描述 / 有余对照 / 补的方式 / 时机判断

## 三、新闻后果推演（不可跳过！）
选至少2条最重要的动态，按**纵向推演+横向定位**分析：

### A. 5层传导（纵向推演）
- 第1层→第2层→第3层→第4层→判断

### B. 天之道定位（横向定位）
> 天之道，损有余而补不足。市场短期走"人之道"（马太效应），长期走"天之道"（均值回归）。

四步分析法：
1. **有余（被损方）**：供给过剩/估值过高/关注过度 → 被损
2. **不足（被补方）**：供给短缺/估值偏低/关注不足 → 被补
3. **再平衡方向**：市场如何自发修正？速度？阻力？赢家/输家？
4. **行动含义**：站在哪边？时机？风险？

## 四、逆潮观察（反直觉判断）
找出2-3条"多数人这么想，但反过来才对"的判断：
- **多数人观点**：当前主流看法
- **逆潮判断**：为什么多数人错了
- **逻辑支撑**：推演链条
- **行动含义**：现在该做什么

必须真的反直觉，不能是"看好但要注意风险"这种假反直觉。每条判断要有可证伪条件。

## 五、投资机会与创业项目
### A. 投资机会
1. 供需错配方向（有余vs不足） 2. 政策红利窗口 3. 技术降维机会 4. 跨境信息差套利

### B. 创业项目
优先从**今天发现的缺口**中推荐1个最高落地性项目，不再限定固定方向。
包含：具体做什么/需要多少钱/第一步干什么/预期收益/风险和退出方式

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
    """检查某日某任务是否已执行（含成功和部分成功）"""
    rows = db_exec(
        "SELECT success FROM executed_tasks WHERE date=? AND task_name=?",
        (date_str, task_name), fetch=True
    )
    return bool(rows and rows[0][0])


def is_task_fully_completed(date_str, task_name):
    """检查某日某任务是否完全完成（内容生成+邮件发送都成功）"""
    rows = db_exec(
        "SELECT success FROM executed_tasks WHERE date=? AND task_name=?",
        (date_str, task_name), fetch=True
    )
    return bool(rows and rows[0][0])


def was_task_attempted(date_str, task_name):
    """检查某日某任务是否尝试过（不管成功失败）"""
    rows = db_exec(
        "SELECT 1 FROM executed_tasks WHERE date=? AND task_name=?",
        (date_str, task_name), fetch=True
    )
    return bool(rows)


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



def generate_with_hunyuan(task_name, system_prompt, user_prompt, max_tokens=8000, timeout=60):
    """用混元API生成内容，失败回退办公室Qwen3.6"""
    # 优先混元（超时60秒）
    result = _call_api(
        task_name=task_name,
        base_url=HUNYUAN_BASE_URL,
        api_key=HUNYUAN_API_KEY,
        model='hunyuan-turbos-latest',
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    if result:
        return result
    logging.warning(f"[{task_name}] 混元失败，尝试办公室Qwen3.6...")
    
    # 回退办公室Qwen3.6（超时90秒）
    if OFFICE_ENABLED:
        result = _call_api(
            task_name=task_name,
            base_url=OFFICE_API_BASE,
            api_key=OFFICE_API_KEY,
            model=OFFICE_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            timeout=90,
        )
        if result:
            return result
        logging.warning(f"[{task_name}] 办公室Qwen3.6失败，使用兜底内容")
    
    # 不再回退，直接返回兜底内容
    logging.error(f"[{task_name}] 所有API失败，使用兜底内容")
    return None


def generate_with_deepseek(task_name, task, today_str):
    """用API生成研究内容 — 优先混合元，失败回退办公室Qwen3.6，再失败回退百炼DeepSeek"""
    user_prompt = task['user_prompt_template'].format(date=today_str)
    system_prompt = task['system_prompt']
    return generate_with_hunyuan(task_name, system_prompt, user_prompt, max_tokens=8000, timeout=180)

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
        reasoning = usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)

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

    # 🔴 占位文本检测（不限长度，任何占位文本都拦截）
    placeholder_patterns = ['详见Gitee仓库', '已完成，详见', '详见仓库', '详见Gitee']
    if any(p in content for p in placeholder_patterns):
        logging.error(f"[邮件] 内容包含占位文本，不发空邮件！内容前200字: {content[:200]}")
        return False

    subject = subject_override or f"{task['email_subject_prefix']} | {today_str}"

    # 🔴 将markdown转成HTML，确保邮件正常渲染（163邮箱对pre-wrap+长文本渲染差）
    html_content = markdown.markdown(content, extensions=['tables', 'fenced_code', 'nl2br'])

    body = f"""<html><head><meta charset="utf-8">
<style>
body {{ font-family: -apple-system, 'Microsoft YaHei', sans-serif; font-size: 15px; line-height: 1.8; color: #222; max-width: 720px; margin: 0 auto; padding: 16px; background: #fff; }}
h1 {{ font-size: 18px; font-weight: 600; border-bottom: 1px solid #ccc; padding-bottom: 6px; color: #222; }}
h2 {{ font-size: 16px; font-weight: 600; color: #222; margin-top: 24px; padding-bottom: 4px; }}
h3 {{ font-size: 15px; font-weight: 600; color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ border: 1px solid #ddd; padding: 5px 8px; text-align: center; font-size: 14px; }}
th {{ background: #f8f8f8; font-weight: 600; }}
blockquote {{ border-left: 2px solid #999; padding-left: 10px; color: #555; margin: 10px 0; }}
strong {{ font-weight: 600; }}
code {{ background: #f5f5f5; padding: 1px 3px; border-radius: 2px; font-size: 13px; }}
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


def _format_liuhai_digest(digest, source='⏰ 凌晨摘要'):
    """将刘海蟾凌晨摘要格式化为markdown彩票板块"""
    lines = []
    lines.append('\n---\n')
    lines.append('## 🎰 刘海蟾点金 — 今日推荐')
    lines.append(f'> 数据来源: {source} | 运行时间: {digest.get("generated_at", "?")} | GEPA: {digest.get("steps", {}).get("gepa", "?")}')

    weights = digest.get('weights_used', {})
    if weights:
        w_str = ' '.join(f'{k}={v}' for k, v in weights.items() if v is not None)
        lines.append(f'> 全局权重: {w_str}')

    recs = digest.get('recommendations', {})
    game_names = {'qxc': '七星彩', 'ssq': '双色球', 'dlt': '大乐透'}

    for game_key in ['qxc', 'ssq', 'dlt']:
        game_recs = recs.get(game_key, [])
        if not game_recs:
            continue
        lines.append(f'\n### {game_names.get(game_key, game_key)}')
        for i, rec in enumerate(game_recs, 1):
            strategy = rec.get('strategy', '?')
            if game_key == 'qxc':
                digits = rec.get('digits', [])
                num_str = ' '.join(str(d) for d in digits)
                lines.append(f'  注{i}: **{num_str}**  [{strategy}]')
            elif game_key == 'ssq':
                reds = rec.get('reds', [])
                blue = rec.get('blue', '?')
                num_str = ' '.join(str(r).zfill(2) for r in reds)
                lines.append(f'  注{i}: **{num_str}** + 蓝**{str(blue).zfill(2)}**  [{strategy}]')
            elif game_key == 'dlt':
                front = rec.get('front', [])
                back = rec.get('back', [])
                front_str = ' '.join(str(f).zfill(2) for f in front)
                back_str = ' '.join(str(b).zfill(2) for b in back)
                lines.append(f'  注{i}: **{front_str}** + **{back_str}**  [{strategy}]')

    # GEPA变更说明
    changes = digest.get('gepa_changes', [])
    if changes:
        lines.append(f'\n**GEPA调整**: {"; ".join(changes[:5])}')

    steps = digest.get('steps', {})
    pred = steps.get('predict', '?')
    settle = steps.get('settle', '?')
    lines.append(f'\n> 虚拟用户: 预测{pred}条 / 结算{settle}条 / 演化模板+{steps.get("evolver", 0)}个')
    lines.append('\n---\n')

    return '\n'.join(lines)


def run_task_and_email(task_name, task, today_str):
    """生成内容 + 写文件 + 发邮件"""
    task['name'] = task_name

    # 🟢 检查DB中是否已完全完成（内容+邮件都成功），防止重复生成浪费token
    if is_task_fully_completed(today_str, task_name):
        logging.info(f"[{task_name}] 今日已完全完成（内容+邮件），跳过")
        return True

    # 🔴 如果尝试过但邮件没发成，只补发邮件，不重新生成内容
    if was_task_attempted(today_str, task_name):
        output_file = find_today_file(task.get('output_dir', ''), today_str)
        if output_file and not is_already_sent(task_name, output_file):
            logging.info(f"[{task_name}] 今日已生成内容但邮件未发送，补发邮件")
            send_task_email(task, today_str, output_file)
            # 重新检查是否发送成功，更新DB
            if is_already_sent(task_name, output_file):
                mark_task_executed(today_str, task_name, True)
                return True
            else:
                logging.warning(f"[{task_name}] 补发邮件仍然失败")
                return False
        elif output_file and is_already_sent(task_name, output_file):
            mark_task_executed(today_str, task_name, True)
            return True
        else:
            logging.info(f"[{task_name}] 之前尝试过但无输出文件，重新执行")

    # 第一步：生成内容
    content = generate_with_deepseek(task_name, task, today_str)

    # 🔴 防护：如果API返回占位文本，重试一次（不限长度，任何占位模式都拦截）
    placeholder_patterns = ['详见Gitee仓库', '已完成，详见', '详见仓库', '详见Gitee', '已完成']
    def is_placeholder(text):
        return text and any(p in text for p in placeholder_patterns)

    if is_placeholder(content):
        logging.warning(f"[{task_name}] API返回了占位文本，5秒后重试... 内容前200字: {content[:200]}")
        time.sleep(5)
        content = generate_with_deepseek(task_name, task, today_str)
        if is_placeholder(content):
            logging.error(f"[{task_name}] 重试后仍返回占位文本，放弃")
            content = None

    # 🔴 第二步：彩票推荐（优先读刘海蟾摘要，摘要不新鲜就先跑daily_run，最后fallback旧版）
    lottery_section = ''
    lottery_source = '❓'  # 来源标记，邮件里能看到

    # 🔴 路径适配：GitHub Actions checkout两个仓库时，目录结构不同
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _is_github_actions = os.environ.get('RUN_ENV') == 'github-actions' or os.environ.get('GITHUB_ACTIONS') == 'true'
    if _is_github_actions:
        # GitHub Actions: 两个仓库同级checkout到 $GITHUB_WORKSPACE 下
        _workspace = os.environ.get('GITHUB_WORKSPACE', '/__w/asuan-scheduler/asuan-scheduler')
        LIUHAI_DIGEST = os.path.join(_workspace, 'liuhai-chan', 'backend', 'data', 'lottery-digest.json')
        LIUHAI_DAILY_RUN = os.path.join(_workspace, 'liuhai-chan', 'backend', 'daily_run.py')
    else:
        # 本地: 相对路径 ../liuhai-chan/
        LIUHAI_DIGEST = os.path.join(_script_dir, '..', 'liuhai-chan', 'backend', 'data', 'lottery-digest.json')
        LIUHAI_DAILY_RUN = os.path.join(_script_dir, '..', 'liuhai-chan', 'backend', 'daily_run.py')

    # 检查摘要是否新鲜（日期匹配）
    digest_fresh = False
    if os.path.exists(LIUHAI_DIGEST):
        try:
            with open(LIUHAI_DIGEST, 'r', encoding='utf-8') as f:
                digest = json.load(f)
            if digest.get('date') == today_str:
                digest_fresh = True
                lottery_source = '⏰ 凌晨摘要'
                logging.info(f"[彩票] 读取刘海蟾摘要: {digest.get('generated_at')}")
                lottery_section = _format_liuhai_digest(digest, source=lottery_source)
                logging.info(f"[彩票] 摘要格式化完成: {len(lottery_section)}字符")
            else:
                logging.warning(f"[彩票] 摘要日期不匹配（{digest.get('date')} vs {today_str}）")
        except Exception as e:
            logging.error(f"[彩票] 读取摘要失败: {e}")

    # 摘要不新鲜 → 先跑刘海蟾daily_run生成一份
    if not digest_fresh and os.path.exists(LIUHAI_DAILY_RUN):
        try:
            import subprocess
            lottery_source = '🔄 即时运行'
            logging.info("[彩票] 摘要不新鲜，先跑刘海蟾daily_run...")
            result = subprocess.run(
                [sys.executable, LIUHAI_DAILY_RUN],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                logging.info(f"[彩票] daily_run跑完，重新读摘要")
                # 重新读摘要
                if os.path.exists(LIUHAI_DIGEST):
                    with open(LIUHAI_DIGEST, 'r', encoding='utf-8') as f:
                        digest = json.load(f)
                    if digest.get('date') == today_str:
                        lottery_section = _format_liuhai_digest(digest, source=lottery_source)
                        logging.info(f"[彩票] 新摘要格式化完成: {len(lottery_section)}字符")
            else:
                logging.error(f"[彩票] daily_run失败: {result.stderr[:200]}")
        except Exception as e:
            logging.error(f"[彩票] 调用daily_run异常: {e}")

    # 最后兜底：旧版lottery_analyzer
    if not lottery_section:
        lottery_source = '⚠️ 旧版兜底'
        try:
            logging.info("[彩票] 走旧版lottery_analyzer生成推荐...")
            lottery_section = generate_lottery_recommendations()
            # 给旧版输出加上来源标记
            lottery_section = lottery_section.replace(
                '## 🎰', f'## 🎰 刘海蟾点金\n> 数据来源: {lottery_source}\n\n## 🎰', 1
            ) if '## 🎰' in lottery_section else f'\n---\n## 🎰 刘海蟾点金\n> 数据来源: {lottery_source}\n{lottery_section}\n---\n'
            logging.info(f"[彩票] 推荐生成完成: {len(lottery_section)}字符")
        except Exception as e:
            logging.error(f"[彩票] 推荐生成失败: {e}")
            lottery_section = '\n---\n🎰 彩票推荐生成异常，请手动运行lottery_analyzer.py\n---\n'

    # 🟢 v8.0: 算法模块每日更新（结算昨日 + ROI计算 + 策略权重更新）
    try:
        from algo_module import run_algo_daily_update
        run_algo_daily_update()
        logging.info("[Algo] 算法模块每日更新完成")
    except Exception as e:
        logging.warning(f"[Algo] 算法模块每日更新跳过: {e}")

    # 第三步：写入文件（🔴 含彩票内容，保证文件和邮件一致）
    output_file = None
    if content:
        title = '阿算帮刘老板发财日报'
        full_content = f"# {title} — {today_str}\n\n---\n\n{content}{lottery_section}"

        os.makedirs(task['output_dir'], exist_ok=True)
        file_path = os.path.join(task['output_dir'], f"{today_str}.md")
        with open(file_path, 'w') as f:
            f.write(full_content)

        logging.info(f"[{task_name}] 文件已写入: {file_path} ({len(full_content)}字符)")

        if '推演' not in full_content:
            logging.warning(f"[{task_name}] ⚠️ 内容缺少'推演'关键词，可能不完整")

        output_file = file_path
    else:
        logging.warning(f"[{task_name}] ⚠️ API生成失败，尝试使用已有文件")

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
        # 生成失败，找最近的文件（包括今天的）
        pattern = os.path.join(task['output_dir'], "*.md")
        files = glob.glob(pattern)
        if files:
            recent = max(files, key=os.path.getmtime)
            logging.info(f"[{task_name}] 使用已有文件: {recent}")
            if not is_already_sent(task_name, recent):
                subject = f"{task['email_subject_prefix']} | {today_str}（使用近期数据）"
                send_task_email(task, today_str, recent, subject_override=subject)
        else:
            subject = f"{task['email_subject_prefix']} | {today_str}（生成异常）"
            body = f"""<p>{task['desc']}生成异常，请手动检查。</p>
            <p>时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p>"""
            send_email(subject, body)

    # 🟢 记录执行状态到DB
    # 🔴 v6.8修复：只有邮件真的发成功才标记success=True，否则标记False让下次重试
    email_sent = False
    if should_send and output_file:
        email_sent = is_already_sent(task_name, output_file)
    elif not should_send:
        email_sent = True  # 不需要发邮件的环境，文件生成就算成功
    success = output_file is not None and email_sent
    if output_file and not email_sent:
        logging.warning(f"[{task_name}] ⚠️ 内容已生成但邮件未发送，标记success=False，下次会补发")
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
    # 🔴 环境检测 — 服务器上允许运行（有SMTP配置）
    run_env = os.environ.get('RUN_ENV', 'sandbox')
    force_run = os.environ.get('FORCE_SANDBOX_RUN', '')
    if run_env == 'sandbox' and not force_run:
        print(f"[阿算] 检测到sandbox环境，但服务器上仍允许执行任务")
        print(f"[阿算] 如需完全禁用，请设置 FORCE_SANDBOX_RUN=1 以外的环境变量")
        # 不exit，继续执行
    elif force_run:
        print(f"[阿算] FORCE_SANDBOX_RUN={force_run}，强制运行")

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
    parser.add_argument('--force', action='store_true', help='Force rerun even if already executed today')
    args = parser.parse_args()

    if args.once:
        # 🔴 单次执行模式（GitHub Actions / 手动调试）
        init_db()
        now = datetime.now(CST)
        today = now.strftime('%Y-%m-%d')
        logging.info(f"单次执行模式: {today}")

        if args.force:
            # 清除今日执行记录，强制重新执行
            logging.info(f"🔴 --force 模式：清除今日执行记录，强制重新执行")
            db_exec("DELETE FROM executed_tasks WHERE date=?", (today,))
            db_exec("DELETE FROM sent_log WHERE sent_at LIKE ?", (f'{today}%',))

        for task_name, task in TASKS.items():
            task['name'] = task_name

            if not is_task_executed(today, task_name):
                # 🔴 情况A：从未执行过，正常跑全流程
                run_task_and_email(task_name, task, today)
            else:
                # 🔴 情况B：标记已执行，但要验证邮件是否真的发了
                output_file = find_today_file(task.get('output_dir', ''), today)
                if output_file and is_already_sent(task_name, output_file):
                    logging.info(f"[{task_name}] 今日已执行且邮件已发送，跳过")
                elif output_file:
                    # 生成了内容但邮件没发出去——补发邮件
                    logging.info(f"[{task_name}] ⚠️ 今日已执行但邮件未发送，补发邮件")
                    send_task_email(task, today, output_file)
                else:
                    # 标记执行了但连输出文件都没有——大概率API失败，清除记录重跑
                    logging.info(f"[{task_name}] ⚠️ 标记已执行但无输出文件，清除记录重新执行")
                    db_exec("DELETE FROM executed_tasks WHERE date=? AND task_name=?", (today, task_name))
                    run_task_and_email(task_name, task, today)
    else:
        main()
