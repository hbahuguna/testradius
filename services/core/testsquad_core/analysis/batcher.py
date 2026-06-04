from typing import List
from testsquad_shared import CodeSymbol, SymbolBatch

class SymbolBatcher:
    def __init__(self, max_tokens_per_batch: int = 4000):
        self.max_tokens_per_batch = max_tokens_per_batch

    def batch(self, symbols: List[CodeSymbol]) -> List[SymbolBatch]:
        """
        Groups symbols into batches based on approximate token count.
        For now, we use a simple character-based approximation (1 token ~= 4 chars).
        """
        batches = []
        current_symbols = []
        current_tokens = 0
        batch_count = 1

        for symbol in symbols:
            # Approximate tokens for symbol content
            content_len = len(symbol.content) if symbol.content else 0
            # Add some overhead for metadata
            symbol_tokens = (content_len // 4) + 50 

            if current_tokens + symbol_tokens > self.max_tokens_per_batch and current_symbols:
                batches.append(SymbolBatch(
                    batch_id=f"batch_{batch_count}",
                    symbols=current_symbols,
                    total_tokens=current_tokens
                ))
                current_symbols = []
                current_tokens = 0
                batch_count += 1

            current_symbols.append(symbol)
            current_tokens += symbol_tokens

        if current_symbols:
            batches.append(SymbolBatch(
                batch_id=f"batch_{batch_count}",
                symbols=current_symbols,
                total_tokens=current_tokens
            ))

        return batches
