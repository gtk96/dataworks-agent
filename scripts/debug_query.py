"""Debug: why can't '查一下订单表' be recognized?"""
from dataworks_agent.agent.nlu.intent_parser import IntentParser
from dataworks_agent.agent.nlu.templates import INTENT_TEMPLATES
import re

parser = IntentParser()
text = "查一下订单表"
text_lower = text.lower()

intent = parser.parse(text)
print(f"Intent: {intent.action}, confidence: {intent.confidence}")
print(f"Params: {intent.params}")
print()

# Check all patterns
print("=== Checking all patterns ===")
for action, template in INTENT_TEMPLATES.items():
    for i, pattern in enumerate(template["patterns"]):
        match = re.search(pattern, text_lower)
        if match:
            print(f"  {action}[{i}] MATCHED: {pattern[:60]}... -> {match.group()}")

# Check DATAWORKS_GOAL_WORDS
from dataworks_agent.agent.nlu.intent_parser import DATAWORKS_GOAL_WORDS
print(f"\n=== DATAWORKS_GOAL_WORDS ===")
for word in DATAWORKS_GOAL_WORDS:
    if word in text_lower:
        print(f"  Found: {word}")

# Check entity extractor
from dataworks_agent.agent.nlu.entity_extractor import EntityExtractor
extractor = EntityExtractor()
table_name = extractor.extract_table_name(text)
print(f"\n=== Entity Extractor ===")
print(f"  table_name: {table_name}")
print(f"  source_table: {extractor.extract_source_table(text)}")
