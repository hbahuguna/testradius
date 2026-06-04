import argparse
import json
import os
from .extractor import SymbolExtractor
from .differ import Differ
from .batcher import SymbolBatcher

def analyze_diff(diff_path: str, repo_root: str):
    if not os.path.exists(diff_path):
        print(f"Error: Diff file not found at {diff_path}")
        return

    with open(diff_path, "r") as f:
        diff_content = f.read()

    differ = Differ()
    modified_lines = differ.get_modified_lines(diff_content)
    
    extractor = SymbolExtractor()
    batcher = SymbolBatcher()
    
    all_modified_symbols = []
    
    for file_path, lines in modified_lines.items():
        # Ah, Differ returns file_path -> Set[int]. I'll use modified_lines.items()
        pass

    # Let me fix the logic below
    
    for file_path, lines in modified_lines.items():
        full_path = os.path.join(repo_root, file_path)
        if not os.path.exists(full_path):
            continue
            
        with open(full_path, "r") as f:
            content = f.read()
            
        symbols = extractor.extract_symbols(file_path, content)
        # Filter symbols that overlap with modified lines
        for symbol in symbols:
            symbol_lines = set(range(symbol.start_line, symbol.end_line + 1))
            if lines.intersection(symbol_lines):
                all_modified_symbols.append(symbol)

    batches = batcher.batch(all_modified_symbols)
    
    print(f"Analysis complete. Found {len(all_modified_symbols)} modified symbols in {len(batches)} batches.")
    for batch in batches:
        print(f"\n{batch.batch_id} ({batch.total_tokens} tokens):")
        for symbol in batch.symbols:
            print(f" - [{symbol.type.value}] {symbol.name} ({symbol.file_path}:{symbol.start_line}-{symbol.end_line})")

def main():
    parser = argparse.ArgumentParser(description="Analyze git diff and extract modified symbols.")
    parser.add_argument("diff", help="Path to the unified diff file.")
    parser.add_argument("--root", default=".", help="Root of the repository.")
    args = parser.parse_args()
    
    analyze_diff(args.diff, args.root)

if __name__ == "__main__":
    main()
