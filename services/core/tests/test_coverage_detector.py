import pytest
import os
from unittest.mock import MagicMock
from testsquad_core.analysis.coverage import CoberturaParser, CoverageMapper

def test_cobertura_parsing():
    # Create a dummy Cobertura XML
    xml_content = """<?xml version="1.0" ?>
<coverage line-rate="0.5" branch-rate="0.5" version="1.9" timestamp="12345678" lines-covered="1" lines-valid="2" branches-covered="0" branches-valid="0" complexity="0">
	<packages>
		<package name="testsquad_core" line-rate="0.5" branch-rate="0.5" complexity="0">
			<classes>
				<class name="analysis_git_py" filename="services/core/testsquad_core/analysis/git.py" complexity="0" line-rate="0.5" branch-rate="0.5">
					<lines>
						<line number="10" hits="1"/>
						<line number="11" hits="0"/>
					</lines>
				</class>
			</classes>
		</package>
	</packages>
</coverage>
"""
    report_path = "/tmp/test_coverage.xml"
    with open(report_path, "w") as f:
        f.write(xml_content)
    
    parser = CoberturaParser()
    data = parser.parse_report(report_path)
    
    assert "services/core/testsquad_core/analysis/git.py" in data
    assert data["services/core/testsquad_core/analysis/git.py"][10] == 1
    assert data["services/core/testsquad_core/analysis/git.py"][11] == 0
    
    os.remove(report_path)

def test_coverage_mapping():
    mock_neo4j = MagicMock()
    mapper = CoverageMapper(mock_neo4j)
    
    # Mock symbols for a file
    mock_neo4j.query.return_value = [
        {"name": "func_ok", "start": 10, "end": 12, "full_path": "file.py"},
        {"name": "func_gap", "start": 20, "end": 22, "full_path": "file.py"}
    ]
    
    coverage_data = {
        "file.py": {
            10: 1, 11: 1, 12: 1,  # func_ok is covered
            20: 1, 21: 0, 22: 1   # func_gap has a gap at 21
        }
    }
    
    mapper.map_coverage(project_id=1, coverage_data=coverage_data)
    
    # Check func_ok call
    mock_neo4j.update_symbol_coverage.assert_any_call(
        "file.py", "func_ok", True, 1.0
    )
    
    # Check func_gap call (1 line missing out of 3 = 0.666...)
    mock_neo4j.update_symbol_coverage.assert_any_call(
        "file.py", "func_gap", False, pytest.approx(0.666, 0.01)
    )
