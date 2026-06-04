import sys
import os

def test_print_path():
    print("\nSYS PATH:")
    for p in sys.path:
        print(f"  {p}")
    print("\nCWD:", os.getcwd())
    print("\nPYTHONPATH:", os.environ.get("PYTHONPATH"))
    
    try:
        from testsquad_executor.sandbox.manager import SandboxManager
        print("\nSUCCESS: Imported SandboxManager")
    except ImportError as e:
        print(f"\nFAILURE: Could not import SandboxManager: {e}")
