import os
import uuid
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

from testsquad_core.instrumentation.testbed_manager import (
    TestbedManager,
    TestbedConfig,
    TestbedResult
)
from testsquad_core.instrumentation.coverage_transformer import (
    CoverageTransformer,
    TestSymbolStore,
    TestSymbolMapping
)
from testsquad_shared.api.contract import (
    InstrumentationRequest,
    InstrumentationResponse,
    TaskStatus
)


class InstrumentationService:
    """
    Orchestration service for instrumentation-based TIA.
    
    Coordinates:
    - TestbedManager for cloning and running tests
    - CoverageTransformer for parsing coverage data
    - TestSymbolStore for Neo4j integration
    """

    def __init__(self, neo4j_client=None):
        self.testbed_manager = TestbedManager()
        self.test_symbol_store = TestSymbolStore(neo4j_client)
        self._runs: Dict[str, Dict[str, Any]] = {}

    async def run_instrumentation(
        self,
        request: InstrumentationRequest
    ) -> InstrumentationResponse:
        """
        Run the full instrumentation pipeline.
        
        Steps:
        1. Clone testbed (use cache if available)
        2. Run tests with instrumentation
        3. Transform coverage to symbol mapping
        4. Store in Neo4j
        5. Return impacted tests
        """
        run_id = str(uuid.uuid4())
        start_time = datetime.now()

        try:
            print(f"[{run_id}] Starting instrumentation for: {request.testbed_name}")

            clone_result = self.testbed_manager.clone_testbed(
                name=request.testbed_name,
                use_cache=request.use_cache
            )

            if not clone_result.success:
                return InstrumentationResponse(
                    run_id=uuid.UUID(run_id),
                    status=TaskStatus.FAILED,
                    testbed_name=request.testbed_name,
                    error_message=f"Clone failed: {clone_result.error_message}",
                    execution_time_seconds=0.0
                )

            testbed_path = clone_result.testbed_path
            config = self.testbed_manager.get_testbed(request.testbed_name)

            if request.run_instrumented_tests:
                print(f"[{run_id}] Running instrumented tests...")
                test_result = self.testbed_manager.run_instrumented_tests(
                    testbed_path=testbed_path,
                    config=config
                )

                if not test_result.success:
                    return InstrumentationResponse(
                        run_id=uuid.UUID(run_id),
                        status=TaskStatus.FAILED,
                        testbed_name=request.testbed_name,
                        testbed_path=testbed_path,
                        error_message=f"Tests failed: {test_result.error_message}",
                        execution_time_seconds=test_result.execution_time_seconds
                    )

                coverage_data = test_result.coverage_data
            else:
                coverage_path = os.path.join(testbed_path, config.coverage_output)
                if os.path.exists(coverage_path):
                    with open(coverage_path, 'r') as f:
                        coverage_data = json.load(f)
                else:
                    coverage_data = None

            if coverage_data and request.store_in_neo4j:
                print(f"[{run_id}] Transforming coverage to symbol mapping...")
                transformer = CoverageTransformer(project_root=testbed_path)
                mappings = transformer.transform(coverage_data)

                print(f"[{run_id}] Storing {len(mappings)} test-symbol mappings in Neo4j...")
                edge_count = self.test_symbol_store.store_mappings(
                    mappings=mappings,
                    project_id=request.project_id
                )
                print(f"[{run_id}] Created {edge_count} test-symbol edges")
            else:
                edge_count = 0

            execution_time = (datetime.now() - start_time).total_seconds()

            self._runs[run_id] = {
                "request": request.model_dump(),
                "testbed_path": testbed_path,
                "coverage_data": coverage_data,
                "mapping_count": edge_count,
                "execution_time": execution_time
            }

            return InstrumentationResponse(
                run_id=uuid.UUID(run_id),
                status=TaskStatus.COMPLETED,
                testbed_name=request.testbed_name,
                testbed_path=testbed_path,
                coverage_data=coverage_data,
                test_symbol_mappings=edge_count,
                execution_time_seconds=execution_time
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            return InstrumentationResponse(
                run_id=uuid.UUID(run_id),
                status=TaskStatus.FAILED,
                testbed_name=request.testbed_name,
                error_message=f"Error: {str(e)}",
                execution_time_seconds=execution_time
            )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a previous instrumentation run."""
        return self._runs.get(run_id)

    def get_impacted_tests(
        self,
        project_id: int,
        changed_symbols: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Get tests impacted by changed symbols.
        
        This queries the Neo4j store for tests that cover the given symbols.
        """
        return self.test_symbol_store.get_impacted_tests(
            project_id=project_id,
            changed_symbols=changed_symbols
        )