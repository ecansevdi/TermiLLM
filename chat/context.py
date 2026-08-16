class ContextManager:
    """Token tahmini, history kırpma ve mesaj oluşturma."""

    def __init__(self, system_prompt: str, safety_ratio: float = 0.85):
        self.system_prompt = system_prompt
        self.safety_ratio = safety_ratio

    def estimate_text(self, text: str) -> int:
        return max(1, len(text) // 4)

    def estimate_messages(self, messages: list) -> int:
        total = self.estimate_text(self.system_prompt) + 10
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        total += self.estimate_text(part.get("text", "")) + 10
            else:
                total += self.estimate_text(content) + 10
        return total

    def trim(self, history: list, budget: int):
        trimmed = False
        while len(history) > 2 and self.estimate_messages(history) > budget:
            history = history[2:]
            trimmed = True
        return history, trimmed

    def build_messages(self, history: list) -> list:
        return [{"role": "system", "content": self.system_prompt}] + history

    def calculate_budget(self, max_context_tokens: int) -> int:
        return int(max_context_tokens * self.safety_ratio)
