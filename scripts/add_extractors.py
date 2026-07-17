"""Add extractors for any_ods_modeling params"""
with open('dataworks_agent/agent/nlu/entity_extractor.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add new extraction methods before extract_params
new_methods = '''
    def extract_holo_schema(self, text: str) -> str | None:
        """Extract Hologres schema name."""
        match = re.search(
            r"(?:holo[_\\s]?schema|holo\\s+schema|holo\\s+\\.?)\\s*(?:\\u4e3a|\\u662f|[:\\uff1a])?\\s*([a-zA-Z][a-zA-Z0-9_]*)",
            text, re.IGNORECASE
        )
        if match:
            return match.group(1)
        # Also match holo_schema.xxx pattern
        match = re.search(r"holo[_\\s]?schema[_\\s]*[:\\uff1a]\\s*([a-zA-Z][a-zA-Z0-9_]*)", text, re.IGNORECASE)
        return match.group(1) if match else None

    def extract_database(self, text: str) -> str | None:
        """Extract database name for MySQL/PG."""
        match = re.search(
            r"(?:database|\\u5e93|db)\\s*(?:\\u4e3a|\\u662f|[:\\uff1a])?\\s*([a-zA-Z][a-zA-Z0-9_]*)",
            text, re.IGNORECASE
        )
        return match.group(1) if match else None

    def extract_sync_mode(self, text: str) -> str | None:
        """Extract sync mode (full/incremental)."""
        lowered = text.lower()
        if any(k in lowered for k in ("增量", "incremental", "incr")):
            return "incremental"
        if any(k in lowered for k in ("全量", "full")):
            return "full"
        return None

    def extract_incremental_column(self, text: str) -> str | None:
        """Extract incremental sync column."""
        match = re.search(
            r"(?:增量\\u5b57\\u6bb5|incremental\\s*column|\\u589e\\u91cf\\u5217)\\s*(?:\\u4e3a|\\u662f|[:\\uff1a])?\\s*([a-zA-Z_][a-zA-Z0-9_]*)",
            text, re.IGNORECASE
        )
        return match.group(1) if match else None

'''

# Insert before extract_params
insert_point = content.find('    def extract_params(')
if insert_point < 0:
    print('ERROR: extract_params not found')
    exit(1)

content = content[:insert_point] + new_methods + content[insert_point:]

with open('dataworks_agent/agent/nlu/entity_extractor.py', 'w', encoding='utf-8') as f:
    f.write(content)

# Verify
try:
    compile(content, 'entity_extractor.py', 'exec')
    print('SUCCESS: entity_extractor.py updated')
except SyntaxError as e:
    print(f'SYNTAX ERROR: {e}')
