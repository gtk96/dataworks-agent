"""Refine any_ods_modeling patterns to be less greedy"""
with open('dataworks_agent/agent/nlu/templates.py', encoding='utf-8') as f:
    content = f.read()

# Find and replace the any_ods_modeling patterns
old_patterns = '''        "patterns": [
            # OSS 数据源
            r"(oss|对象存储|\\.json|\\.csv|\\.parquet).*?(ods|入仓|贴源|建模)",
            r"oss_path.*?ods",
            # Holo 数据源
            r"(holo|hologres|实时).*?(ods|入仓|建模)",
            # MySQL/PG 数据源
            r"(mysql|polardb|postgres|关系型).*?(ods|入仓|建模)",
            # 全链路建模 (bidirectional - any order)
            r"(全链路|端到端|完整链路).*?(ods|dwd|dim|dws|建模|数仓)",
            r"(ods|dwd|dim|dws).*?(全链路|端到端|完整链路|建模)",
            # 建表/搭建
            r"(建|搭|创建|搭建).*?(ods|dwd|dws|dim|数仓|建模)",
            r"(ods|dwd|dws|dim).*?(建|搭|创建|搭建|建模)",
            # 通用关键词
            r"全链路.*?建模",
            r"端到端.*?建模",
            r"完整链路.*?建模",
        ],'''

new_patterns = '''        "patterns": [
            # OSS 数据源 (specific to OSS)
            r"oss_path.*?ods",
            r"(oss://|oss\\.cn).*?(ods|入仓|贴源)",
            r"对象存储.*?(ods|入仓|贴源)",
            # Holo 数据源 (specific to Holo)
            r"holo_schema.*?ods",
            r"(holo|hologres).*?(入仓|贴源|ods)",
            # MySQL/PG 数据源 (specific to relational DBs)
            r"(mysql|polardb|postgres|关系型).*?(入仓|贴源|ods)",
            r"jdbc.*?(ods|入仓)",
            # 全链路建模 (must have BOTH chain words AND layer keywords)
            r"全链路.*?(ods|dwd|dim|dws|建模)",
            r"端到端.*?(ods|dwd|dim|dws|建模)",
            r"完整链路.*?(ods|dwd|dim|dws|建模)",
            # 完整链路搭建 (bidirectional)
            r"(全链路|端到端|完整链路).*?(搭建|创建|建模|数仓)",
        ],'''

if old_patterns in content:
    content = content.replace(old_patterns, new_patterns)
    with open('dataworks_agent/agent/nlu/templates.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS: refined patterns')
else:
    print('Pattern not found')
    # Debug
    aom = content.find('"any_ods_modeling"')
    if aom >= 0:
        print(f'Found at {aom}: {content[aom:aom+500]!r}')
