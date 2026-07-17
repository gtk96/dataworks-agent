"""Fix overly greedy any_ods_modeling patterns"""
with open('dataworks_agent/agent/nlu/templates.py', 'r', encoding='utf-8') as f:
    content = f.read()

# The issue is patterns like r"(搭建|创建|建).*?(全链路|ods|dwd|dws|数仓|建模)"
# match "创建ods_user表" which should be create_table
# We need to be more specific - require BOTH a source type AND a chain keyword

old_patterns = '''        "patterns": [
            # OSS 数据源 (specific to OSS)
            r"oss_path.*?ods",
            r"(oss://|oss\\.cn).*?(ods|入仓|贴源|建模)",
            r"对象存储.*?(ods|入仓|贴源|建模)",
            # Holo 数据源 (specific to Holo)
            r"holo_schema.*?ods",
            r"(holo|hologres).*?(入仓|贴源|ods|建模)",
            # MySQL/PG 数据源 (specific to relational DBs)
            r"(mysql|polardb|postgres|关系型).*?(入仓|贴源|ods|建模)",
            r"jdbc.*?(ods|入仓|建模)",
            # 全链路建模 (bidirectional - either order works)
            r"全链路.*?(ods|dwd|dim|dws|建模|数仓)",
            r"(ods|dwd|dim|dws).*?全链路",
            r"端到端.*?(ods|dwd|dim|dws|建模)",
            r"(ods|dwd|dim|dws).*?端到端",
            r"完整链路.*?(ods|dwd|dim|dws|建模)",
            r"(ods|dwd|dim|dws).*?完整链路",
            # 通用搭建/创建
            r"(搭建|创建|建).*?(全链路|ods|dwd|dws|数仓|建模)",
            r"(全链路|ods|dwd|dws).*?(搭建|创建|建)",
            # 关键词组合
            r"(oss|hologres|mysql|polardb|postgres).*?(全链路|端到端|完整链路|建模|入仓)",
        ],'''

new_patterns = '''        "patterns": [
            # OSS 数据源 (specific to OSS)
            r"oss_path.*?ods",
            r"(oss://|oss\\.cn).*?(ods|入仓|贴源)",
            r"对象存储.*?(入仓|贴源|ods)",
            # Holo 数据源 (specific to Holo)
            r"holo_schema.*?ods",
            r"(holo|hologres).*?(入仓|贴源|ods)",
            # MySQL/PG 数据源 (specific to relational DBs)
            r"(mysql|polardb|postgres|关系型).*?(入仓|贴源|ods)",
            r"jdbc.*?(ods|入仓)",
            # 全链路建模 (must have BOTH chain words AND layer keywords)
            r"全链路.*?(ods|dwd|dim|dws)",
            r"(ods|dwd|dim|dws).*?全链路",
            r"端到端.*?(ods|dwd|dim|dws)",
            r"(ods|dwd|dim|dws).*?端到端",
            r"完整链路.*?(ods|dwd|dim|dws)",
            r"(ods|dwd|dim|dws).*?完整链路",
            # 关键词组合 (require source type + modeling keyword)
            r"(oss|hologres|mysql|polardb|postgres).*?(全链路|端到端|完整链路|入仓)",
            r"(全链路|端到端|完整链路).*?(oss|hologres|mysql|polardb|postgres)",
        ],'''

if old_patterns in content:
    content = content.replace(old_patterns, new_patterns)
    with open('dataworks_agent/agent/nlu/templates.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS: patterns tightened')
else:
    print('Pattern not found')
