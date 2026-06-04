import pytest
from pydantic import BaseModel
from testsquad_core.intelligence.sentinel import JSONSentinel

class MockModel(BaseModel):
    name: str
    age: int

def test_json_sentinel_clean_markdown():
    raw = "Here is the result: ```json\n{\"name\": \"John\", \"age\": 30}\n```"
    clean = JSONSentinel.clean_json_string(raw)
    assert clean == "{\"name\": \"John\", \"age\": 30}"

def test_json_sentinel_parse_valid():
    content = "{\"name\": \"Alice\", \"age\": 25}"
    result = JSONSentinel.parse_and_validate(content, MockModel)
    assert result.name == "Alice"
    assert result.age == 25

def test_json_sentinel_parse_malformed_then_clean():
    content = "```json\n{\"name\": \"Bob\", \"age\": 40}\n```"
    result = JSONSentinel.parse_and_validate(content, MockModel)
    assert result.name == "Bob"
    assert result.age == 40

def test_json_sentinel_parse_invalid_schema():
    content = "{\"name\": \"Charlie\", \"age\": \"invalid\"}"
    with pytest.raises(Exception):
        JSONSentinel.parse_and_validate(content, MockModel)
