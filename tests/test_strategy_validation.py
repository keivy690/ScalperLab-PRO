import unittest

from scalperlab.strategy_validation import validate_strategy


class StrategyValidationTests(unittest.TestCase):
    def test_python_source_is_parsed_without_execution(self):
        source = "import os\nopen('sentinel.txt', 'w').write('no')\ndef signal():\n    return True\n"
        result = validate_strategy("candidate.py", source)
        self.assertTrue(result["ok"])
        self.assertIn("os", result["warnings"][0])
        self.assertFalse(__import__("pathlib").Path("sentinel.txt").exists())

    def test_python_syntax_error_is_rejected(self):
        result = validate_strategy("broken.py", "def signal(:\n    pass")
        self.assertFalse(result["ok"])
        self.assertIn("sintaxe", result["summary"].lower())

    def test_mql5_balances_delimiters_and_warns_on_external_calls(self):
        result = validate_strategy("strategy.mq5", "void OnTick() { WebRequest(\"https\"); }")
        self.assertTrue(result["ok"])
        self.assertTrue(result["warnings"])

    def test_mql5_unbalanced_delimiter_is_rejected(self):
        result = validate_strategy("strategy.mq5", "void OnTick() { if(true) {")
        self.assertFalse(result["ok"])

    def test_unknown_extension_is_rejected(self):
        result = validate_strategy("strategy.ex5", "binary")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
