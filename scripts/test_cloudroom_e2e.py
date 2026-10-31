#!/usr/bin/env python3
"""E2E spike test for Cloud Room integration."""
import os
import sys
from pathlib import Path

from harness.execution import create_executor, ExecutorConfig
from harness.integrations.cloudroom import CloudRoomClient


def test_e2e_spike():
    """Test Cloud Room integration end-to-end."""
    # Check config
    token = os.environ.get("CLOUDROOM_TOKEN") or os.environ.get("CLOUDROOM_API_TOKEN")
    if not token:
        print("SKIP: CLOUDROOM_TOKEN not set")
        return
    
    try:
        client = CloudRoomClient()
        # Try to connect
        try:
            caps = client.capabilities()
            print(f"Connected to Cloud Room: {caps}")
        except Exception as e:
            print(f"Connection failed: {e}")
            return
        
        # Create executor
        plan = {"testCases": [{"id": "TC1", "title": "Homepage check", "steps": ["navigate"], "expectedChecks": ["page loads"]}]}
        config = ExecutorConfig(
            run_id="e2e-spike-001",
            target_url="https://testradius.dev",
            plan=plan,
            artifacts_dir=Path("artifacts"),
        )
        
        executor = create_executor(config, executor_type="cloudroom")
        print(f"Created executor: {type(executor).__name__}")
        
        # Test prepare
        prepared = executor.prepare()
        print(f"Prepare: {prepared}, session: {executor.session_id}")
        
        if prepared and executor.session_id:
            print("E2E spike basic flow works")
            executor.cleanup()
        else:
            print("Prepare failed or no session")
            
    except Exception as e:
        print(f"E2E spike failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_e2e_spike()
