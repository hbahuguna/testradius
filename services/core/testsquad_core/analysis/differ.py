from typing import Dict, Set
from unidiff import PatchSet

class Differ:
    @staticmethod
    def get_modified_lines(diff_content: str) -> Dict[str, Set[int]]:
        """
        Parses a unified diff and returns a mapping of file_path -> set of modified/added line numbers.
        """
        patch = PatchSet(diff_content)
        modified_files = {}

        for patched_file in patch:
            if patched_file.is_binary_file:
                continue
            
            file_path = patched_file.path
            # Normalize path if it starts with a/ or b/
            if file_path.startswith("a/"):
                file_path = file_path[2:]
            elif file_path.startswith("b/"):
                file_path = file_path[2:]

            line_numbers = set()
            for hunk in patched_file:
                for line in hunk:
                    if line.is_added or line.is_context: # We only care about the new state
                        if line.target_line_no:
                            # Only track lines that are part of the 'new' version of the file
                            if line.is_added:
                                line_numbers.add(line.target_line_no)
            
            if line_numbers:
                modified_files[file_path] = line_numbers
        
        return modified_files
