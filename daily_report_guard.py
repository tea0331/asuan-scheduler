#!/usr/bin/env python3
"""
日报质量守护 — 每次发送前验证6大板块完整性+内容动态性
阿策铁律第9条：内容契约律

用法：
  python3 daily_report_guard.py [日报文件路径]
  或在scheduler中：from daily_report_guard import validate_report
"""
import sys
import re

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
    # 禁止出现的硬编码内容（一旦出现=阿策在塞假内容）
    "static_patterns": [
        "价格不会凭空涨——一定有传导链",      # 硬编码邪修金句
        "铜→硫酸→磷肥→粮食",               # 硬编码传导链1
        "AI算力→英伟达→散热/电源→VC均热板", # 硬编码传导链2
        "出口退税→跨境结算→汇率对冲",        # 硬编码传导链3
        "铜涨价→台湾冶炼厂→大陆PCB厂",      # 硬编码掮客例子
        "苹果供应链转单→提前卡位替代材料",    # 硬编码掮客例子
        "大陆限电→台湾产能补位",             # 硬编码掮客例子
        "AI宕机，邪修闭关，明日再战",        # fallback金句
    ],
    # 每个板块必须包含的关键要素
    "section_keywords": {
        "每日资讯": ["落地动作", "💰"],
        "缺口扫描": ["缺口", "收钱"],
        "逆潮观察": ["逆向", "下注"],
        "深度传导分析": ["传导链", "天之道"],
        "避坑提醒": ["坑", "止损"],
        "邪修金句": ["💭"],
    },
    # 禁止出现的关键词（出现=降级标志）
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
            # 检查板块内容长度
            # 找到板块标题位置，截取到下一个板块或文末
            idx = content.index(section_header)
            # 找下一个 ## 标题
            next_section = content.find("\n## ", idx + len(section_header))
            if next_section == -1:
                next_section = len(content)
            section_content = content[idx:next_section]
            # 去掉标题行
            body = "\n".join(section_content.split("\n")[1:])
            if len(body.strip()) < DAILY_REPORT_CONTRACT["min_chars_per_section"]:
                errors.append(
                    f"❌ 板块[{section_name}]内容过短: {len(body.strip())}字 "
                    f"< 最低{DAILY_REPORT_CONTRACT['min_chars_per_section']}字"
                )
            # 检查板块关键要素
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

    # 4. 检查总长度（太短=内容被砍）
    if len(content) < 2000:
        errors.append(f"❌ 日报总长度过短: {len(content)}字 < 2000字最低标准")

    # 5. 检查邪修金句是否每天不同（简单检查：如果金句板块和昨天一样=硬编码）
    # 这部分需要在调用端比较，这里只做格式检查

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "score": max(0, 100 - len(errors) * 20 - len(warnings) * 5),
    }


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

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
