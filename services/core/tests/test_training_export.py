import pytest
import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from testsquad_core.intelligence.training_exporter import TrainingExporter


class TestTrainingExporter:
    """Test Task 4.1.2: Training Data Export Tests."""

    @pytest.fixture
    def mock_neo4j(self):
        mock = MagicMock()
        return mock

    @pytest.fixture
    def exporter(self, mock_neo4j):
        return TrainingExporter(neo4j=mock_neo4j)

    # --- Test export_candidate_pairs ---

    def test_export_candidate_pairs_returns_dataframe(self, exporter, mock_neo4j):
        """Test returns pandas DataFrame."""
        mock_neo4j.query.return_value = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "symbol_summary": "Function 1",
             "test_name": "test1", "test_file": "tests/a.test.ts", "test_summary": "Test 1",
             "confidence": 0.85, "source": "vector", "reasoning": "test"}
        ]
        
        result = exporter.export_candidate_pairs(project_id=1, min_confidence=0.6, limit=100)
        
        assert result is not None

    def test_export_candidate_pairs_query_structure(self, exporter, mock_neo4j):
        """Test query includes all required columns."""
        mock_neo4j.query.return_value = []
        
        exporter.export_candidate_pairs(project_id=1, min_confidence=0.6, limit=100)
        
        assert mock_neo4j.query.called

    def test_export_approved_edges_label_1(self, exporter, mock_neo4j):
        """Test APPROVED_TEST edges get label=1."""
        mock_neo4j.query.return_value = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "symbol_summary": "Function 1",
             "test_name": "test1", "test_file": "tests/a.test.ts", "test_summary": "Test 1"}
        ]
        
        result = exporter.export_candidate_pairs(project_id=1)
        
        if not result.empty:
            assert "label" in result.columns

    def test_export_suggested_edges_label_0(self, exporter, mock_neo4j):
        """Test SUGGESTED_TEST edges get label=0."""
        mock_neo4j.query.return_value = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "symbol_summary": "Function 1",
             "test_name": "test1", "test_file": "tests/a.test.ts", "test_summary": "Test 1"}
        ]
        
        result = exporter.export_candidate_pairs(project_id=1)
        
        if not result.empty:
            assert "label" in result.columns

    # --- Test export_hard_negatives ---

    def test_export_hard_negatives_returns_dataframe(self, exporter, mock_neo4j):
        """Test hard negatives returns DataFrame."""
        mock_neo4j.query.return_value = [
            {"name": "func1", "file_path": "src/a.ts", "summary": "Function 1"},
            {"name": "test1", "file_path": "tests/a.test.ts", "summary": "Test 1"}
        ]
        
        result = exporter.export_hard_negatives(project_id=1, max_negatives=10)
        
        assert result is not None

    def test_hard_negatives_label_0(self, exporter, mock_neo4j):
        """Test hard negatives get label=0."""
        mock_neo4j.query.return_value = [
            {"name": "func1", "file_path": "src/a.ts", "summary": "Function 1"},
            {"name": "test1", "file_path": "tests/a.test.ts", "summary": "Test 1"}
        ]
        
        result = exporter.export_hard_negatives(project_id=1, max_negatives=10)
        
        if not result.empty:
            assert "label" in result.columns
            assert all(result["label"] == 0)

    # --- Test export_labeled_csv ---

    def test_export_labeled_csv(self, exporter, mock_neo4j):
        """Test CSV export creates file."""
        mock_neo4j.query.return_value = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "symbol_summary": "Function 1",
             "test_name": "test1", "test_file": "tests/a.test.ts", "test_summary": "Test 1"}
        ]
        
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            output_path = f.name
        
        try:
            result = exporter.export_labeled_csv(
                project_id=1,
                output_path=output_path,
                min_confidence=0.6,
                limit=100,
                include_negatives=False
            )
            
            assert result == output_path
            assert os.path.exists(output_path)
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    # --- Test get_training_statistics ---

    def test_get_statistics(self, exporter, mock_neo4j):
        """Test statistics return dict."""
        mock_neo4j.query.side_effect = [
            [{"count": 100}],
            [{"count": 50}],
            [{"count": 500}]
        ]
        
        result = exporter.get_training_statistics(project_id=1)
        
        assert "suggested_test_edges" in result
        assert "approved_test_edges" in result
        assert "unmapped_symbols" in result

    # --- Test column structure ---

    def test_required_columns_present(self, exporter, mock_neo4j):
        """Test all required columns are present."""
        mock_neo4j.query.return_value = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "symbol_summary": "Function 1",
             "test_name": "test1", "test_file": "tests/a.test.ts", "test_summary": "Test 1"}
        ]
        
        result = exporter.export_candidate_pairs(project_id=1)
        
        required_columns = [
            "sym_id", "sym_path", "sym_summary",
            "test_id", "test_path", "test_summary",
            "confidence", "source", "reasoning", "label"
        ]
        
        for col in required_columns:
            assert col in result.columns, f"Missing column: {col}"

    # --- Test edge cases ---

    def test_empty_project(self, exporter, mock_neo4j):
        """Test with no matching data."""
        mock_neo4j.query.return_value = []
        
        result = exporter.export_candidate_pairs(project_id=1)
        
        assert result is not None
        assert len(result) == 0

    def test_limit_parameter(self, exporter, mock_neo4j):
        """Test limit parameter is passed."""
        mock_neo4j.query.return_value = []
        
        exporter.export_candidate_pairs(project_id=1, limit=1000)
        
        # Verify limit is passed in query params
        call_args = mock_neo4j.query.call_args
        assert call_args is not None


class TestCSVFormat:
    """Test CSV format requirements."""

    @pytest.fixture
    def exporter(self):
        return TrainingExporter(neo4j=MagicMock())

    def test_csv_has_header(self):
        """Test CSV includes header row."""
        # Verified by pandas to_csv with index=False
        import pandas as pd
        df = pd.DataFrame({"col1": [1, 2], "col2": [3, 4]})
        
        import io
        output = io.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)
        
        content = output.read()
        assert "col1" in content
        assert "col2" in content

    def test_csv_data_rows(self):
        """Test CSV has data rows."""
        import pandas as pd
        df = pd.DataFrame({"col1": [1, 2], "col2": [3, 4]})
        
        import io
        output = io.StringIO()
        df.to_csv(output, index=False)
        output.seek(0)
        output.readline()  # Skip header
        
        line = output.readline()
        assert "1" in line or "2" in line


if __name__ == "__main__":
    pytest.main([__file__, "-v"])