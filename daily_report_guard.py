#!/usr/bin/env python3
"""
日报质量守护 V6 — 每次发送前验证6大板块完整性+内容动态性+邪修进化
阿策铁律第9条：内容契约律

V6 升级:
  1. 新增邪修传导链检查 (是否动态生成 vs 硬编码模板)
  2. 新增金句日间去重 (与历史金句比对)
  3. 降级标志更严格 (降级模式也必须有6板块)
  4. 日报对比功能 (与昨天日报比对)

⚠️ 本文件修改权限: 仅WorkBuddy，阿策禁止修改
"""
import sys
import os
import re
import json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 日报内容契约 — 不可修改，修改需刘老板批准
# ============================================================
DAILY_REPORT_CONTRACT = {
    # 6大板块，缺一不可
    "required_sections": [
        ("每日资讯", "一、每日资讯"),
        ("缺口扫描", "二、市场/中间人缺口扫描"),
        ("逆潮观察", "三、逆潮观察"),
        ("深度传导分析", "四、深度传导分析"),
        ("避坑提醒", "五、避坑提醒"),
        ("邪修金句", "六、今日邪修金句"),
    ],
    # 每板块至少字数（不含标题行）
    "min_chars_per_section": 50,
    "min_chars_per_section_quote": 30,  # 邪修金句允许更短
    # 禁止出现的硬编码内容（一旦出现=有人在塞假内容）
    "static_patterns": [
        "价格不会凭空涨——一定有传导链",
        "铜→硫酸→磷肥→粮食",
        "AI算力→英伟达→散热/电源→VC均热板",
        "出口退税→跨境结算→汇率对冲",
        "铜涨价→台湾冶炼厂→大陆PCB厂",
        "苹果供应链转单→提前卡位替代材料",
        "大陆限电→台湾产能补位",
        "AI宕机，邪修闭关，明日再战",
    ],
    # 每个板块必须包含的关键要素
    "section_keywords": {
        "每日资讯": ["落地动作", "💰"],
        "缺口扫描": ["缺口", "收钱", "操作卡"],
        "逆潮观察": ["逆向", "下注"],
        "深度传导分析": ["传导", "天之道"],
        "避坑提醒": ["止损"],
        "邪修金句": ["金句", "邪修"],  # 不检查特定emoji
    },
    # 降级标志 (出现=降级运行 — V7: 诚实标注降级视为已处理)
    "degradation_markers": [
        "AI分析生成失败",
        "今日暂无",
        "下次自动恢复",
        "AI生成失败，请手动分析",
        "AI宕机",
        "模块维护中",
    ],
}


def validate_report(content: str) -> dict:
    """验证日报内容是否符合契约"""
    errors = []
    warnings = []

    # 1. 检查6大板块完整性
    for section_name, section_header in DAILY_REPORT_CONTRACT["required_sections"]:
        if section_header not in content:
            errors.append(f"❌ 缺少板块: [{section_name}] 期望标题'{section_header}'")
        else:
            # 检查板块内容长度（邪修金句跳过长度检查）
            if "邪修金句" not in section_name:
                idx = content.index(section_header)
                next_section = content.find("\n## ", idx + len(section_header))
                if next_section == -1:
                    next_section = len(content)
                section_content = content[idx:next_section]
                body = "\n".join(section_content.split("\n")[1:])
                if len(body.strip()) < DAILY_REPORT_CONTRACT["min_chars_per_section"]:
                    errors.append(
                        f"❌ 板块[{section_name}]内容过短: {len(body.strip())}字 "
                        f"< 最低{DAILY_REPORT_CONTRACT['min_chars_per_section']}字"
                    )
            else:
                # 邪修金句只检查是否包含💭
                if "💭" not in content:
                    errors.append(f"❌ 板块[邪修金句]缺少金句标记💭")
            # 检查板块关键要素（邪修金句跳过）
            if "邪修金句" not in section_name:
                keywords = DAILY_REPORT_CONTRACT["section_keywords"].get(section_name, [])
                missing_kw = [kw for kw in keywords if kw not in section_content]
                if missing_kw:
                    warnings.append(
                        f"⚠️ 板块[{section_name}]缺少关键要素: {missing_kw}"
                    )

    # 2. 检查硬编码内容
    for pattern in DAILY_REPORT_CONTRACT["static_patterns"]:
        if pattern in content:
            errors.append(f"❌ 检测到硬编码内容: '{pattern[:30]}...' — 日报内容必须是动态生成的")

    # 3. 检查降级标志
    degradation_found = []
    for marker in DAILY_REPORT_CONTRACT["degradation_markers"]:
        count = content.count(marker)
        if count > 0:
            degradation_found.append(f"'{marker}'×{count}")
    if degradation_found:
        warnings.append(f"⚠️ 检测到降级标志: {', '.join(degradation_found)}")

    # 3.5 检查过期年份 — AI可能用训练数据中的旧日期
    current_year = datetime.now(CST).year
    stale_years = [str(y) for y in range(2020, current_year)]
    # 只检查窗口期/周期相关上下文中的年份
    gap_section = _extract_section(content, "二、市场/中间人缺口扫描")
    if gap_section:
        for sy in stale_years:
            if sy in gap_section:
                warnings.append(f"⚠️ [时间] 缺口扫描出现过期年份{sy}，当前是{current_year}年，AI可能用了旧数据")
                break

    # 4. 检查总长度
    if len(content) < 2000:
        errors.append(f"❌ 日报总长度过短: {len(content)}字 < 2000字最低标准")

    # 5. 邪修专项检查: 传导链是否看起来像模板
    chain_section = _extract_section(content, "四、深度传导分析")
    if chain_section:
        # 检查5层传导是否都有具体内容(不是"第N层: "后面直接换行)
        chain_lines = [l for l in chain_section.split('\n') if re.match(r'^-.*第\d+层', l.strip())]
        if len(chain_lines) < 3:
            warnings.append("⚠️ [邪修] 传导链层数不足3层，可能内容不完整")

        # 检查天之道是否出现
        if "天之道" not in chain_section:
            warnings.append("⚠️ [邪修] 缺少'天之道'解读")
        if "邪修之道" not in chain_section:
            warnings.append("⚠️ [邪修] 缺少'邪修之道'收钱路径")

    # 6. 邪修专项: 金句去重检查
    quote_match = re.search(r'六、今日邪修金句\s*(.*?)$', content, re.MULTILINE)
    if quote_match:
        today_quote = quote_match.group(1).strip().replace('💭', '').strip()
        if today_quote:
            # 与历史金句比对
            memory_path = os.path.join(MODULE_DIR, 'xie_xiu_memory.json')
            if os.path.exists(memory_path):
                try:
                    with open(memory_path, 'r', encoding='utf-8') as f:
                        memory = json.load(f)
                    recent_quotes = memory.get('quotes', [])[-7:]
                    if today_quote in recent_quotes:
                        errors.append(f"❌ [邪修] 金句与近期重复: '{today_quote[:30]}...'")
                except Exception:
                    pass

    # 7. 缺口扫描检查
    gap_section = _extract_section(content, "二、市场/中间人缺口扫描")
    if gap_section:
        if "收钱模式" not in gap_section:
            warnings.append("⚠️ [缺口] 缺少'收钱模式'")
        if "窗口期" not in gap_section:
            warnings.append("⚠️ [缺口] 缺少'窗口期'")

    # 8. V14: 落地动作质量检查 — 是否有具体数值
    news_section = _extract_section(content, "一、每日资讯")
    if news_section:
        # 统计落地动作条数
        action_lines = [l for l in news_section.split('\n') if '💰' in l or '落地动作' in l]
        if action_lines:
            # 检查有多少条落地动作包含具体数值（金额/百分比）
            action_with_numbers = [l for l in action_lines if re.search(r'\d+[%万台币元万]', l)]
            if len(action_with_numbers) < 3 and len(action_lines) >= 3:
                warnings.append(f"⚠️ [落地动作] 含具体数值的落地动作不足3条({len(action_with_numbers)}/{len(action_lines)})，可能过于空泛")

    # 9. V14: 去模板化检查 — "以「」名义"句式重复>2次视为模板化
    template_pattern = re.findall(r'以「[^」]{2,15}」(名义|身份|背景)', content)
    if len(template_pattern) > 4:
        warnings.append(f"⚠️ [模板化] 检测到{len(template_pattern)}次'以「XX」名义/身份'句式，落地动作可能模板化")

    # 10. V14: 邪修传导链实体引用检查 — 每层是否引用了具体新闻实体
    if chain_section:
        chain_lines = [l.strip() for l in chain_section.split('\n') if re.match(r'^-.*第\d+层', l.strip())]
        # 检查每层是否包含引号内容（引用具体实体）或数字
        layers_with_detail = 0
        for cl in chain_lines:
            if re.search(r'[「」""]', cl) or re.search(r'\d+', cl):
                layers_with_detail += 1
        if len(chain_lines) >= 3 and layers_with_detail < 2:
            warnings.append(f"⚠️ [邪修] 传导链{len(chain_lines)}层中仅{layers_with_detail}层有具体实体引用，可能过于模板化")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "score": max(0, 100 - len(errors) * 20 - len(warnings) * 5),
    }


def _extract_section(content: str, header: str) -> str:
    """提取某个板块的完整内容"""
    if header not in content:
        return ""
    idx = content.index(header)
    next_section = content.find("\n## ", idx + len(header))
    if next_section == -1:
        next_section = len(content)
    return content[idx:next_section]


def compare_with_yesterday(today_content: str) -> dict:
    """与昨天日报比对，检测内容雷同"""
    yesterday_str = (datetime.now(CST) - timedelta(days=1)).strftime('%Y-%m-%d')
    yesterday_path = os.path.join(MODULE_DIR, 'output', f'{yesterday_str}.md')

    result = {"compared": False, "issues": []}

    if not os.path.exists(yesterday_path):
        return result

    try:
        with open(yesterday_path, 'r', encoding='utf-8') as f:
            yesterday_content = f.read()
        result["compared"] = True

        # 1. 金句相同?
        today_quote = _extract_quote(today_content)
        yesterday_quote = _extract_quote(yesterday_content)
        if today_quote and yesterday_quote and today_quote == yesterday_quote:
            result["issues"].append(f"❌ 邪修金句与昨天完全相同: '{today_quote[:30]}'")

        # 2. 传导链完全相同?
        today_chain = _extract_section(today_content, "四、深度传导分析")
        yesterday_chain = _extract_section(yesterday_content, "四、深度传导分析")
        if today_chain and yesterday_chain and today_chain == yesterday_chain:
            result["issues"].append("❌ 传导链与昨天完全相同 — 可能是硬编码")

        # 3. 字数差异过大
        today_len = len(today_content)
        yesterday_len = len(yesterday_content)
        if yesterday_len > 0:
            diff_ratio = abs(today_len - yesterday_len) / yesterday_len
            if diff_ratio > 0.5:
                result["issues"].append(
                    f"⚠️ 字数差异较大: 今天{today_len}字 vs 昨天{yesterday_len}字 "
                    f"(差异{diff_ratio:.0%})"
                )

    except Exception as e:
        result["issues"].append(f"⚠️ 比对异常: {e}")

    return result


def _extract_quote(content: str) -> str:
    """提取邪修金句"""
    match = re.search(r'六、今日邪修金句\s*(.*?)$', content, re.MULTILINE)
    if match:
        return match.group(1).strip().replace('💭', '').strip()
    return ""


def main():
    if len(sys.argv) < 2:
        print("用法: python3 daily_report_guard.py <日报文件路径>")
        sys.exit(1)

    filepath = sys.argv[1]
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"❌ 无法读取文件: {e}")
        sys.exit(1)

    result = validate_report(content)

    print(f"日报质量检查: {'✅ 通过' if result['valid'] else '❌ 不通过'} (得分: {result['score']}/100)")
    print()

    if result["errors"]:
        print("=== 错误 ===")
        for err in result["errors"]:
            print(f"  {err}")
        print()

    if result["warnings"]:
        print("=== 警告 ===")
        for warn in result["warnings"]:
            print(f"  {warn}")

    # 与昨天比对
    compare_result = compare_with_yesterday(content)
    if compare_result["compared"]:
        print()
        print("=== 日间对比 ===")
        if compare_result["issues"]:
            for issue in compare_result["issues"]:
                print(f"  {issue}")
        else:
            print("  ✅ 与昨天日报无异常雷同")

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
