"""Test what intent '创建ods_user表' matches"""
from dataworks_agent.agent.nlu.intent_parser import IntentParser

parser = IntentParser()
intent = parser.parse("创建ods_user表")
print(f"Action: {intent.action}")
print(f"Confidence: {intent.confidence}")
print(f"Params: {intent.params}")
