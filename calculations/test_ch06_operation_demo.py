"""Regression coverage for receipt redaction in the teaching memory interface."""
import unittest

from calculations.ch06_operation_demo import Memory


class ReceiptRedactionTests(unittest.TestCase):
    def test_cross_scope_unknown_action_redacts_receipt_and_event(self):
        memory = Memory()
        memory.apply('create', 'ADD', 'item', 'project-A', value='fixture-private-value')

        receipt = memory.apply('invalid', 'UNKNOWN', 'item', 'project-B')

        self.assertFalse(receipt['applied'])
        self.assertEqual(receipt['reason'], 'unsupported_action')
        self.assertIsNone(receipt['before'])
        self.assertIsNone(receipt['after'])
        self.assertEqual(memory.events[-1], receipt)
        self.assertEqual(memory.read('project-A')['item']['value'], 'fixture-private-value')
        self.assertEqual(memory.read('project-B'), {})
        self.assertEqual(memory.apply('invalid', 'UNKNOWN', 'item', 'project-B'), receipt)
        self.assertEqual(len(memory.events), 2)

    def test_same_scope_unknown_action_preserves_receipt_semantics(self):
        memory = Memory()
        created = memory.apply('create', 'ADD', 'item', 'project-A', value='fixture-value')

        rejected = memory.apply('invalid', 'UNKNOWN', 'item', 'project-A')

        self.assertFalse(rejected['applied'])
        self.assertEqual(rejected['reason'], 'unsupported_action')
        self.assertEqual(rejected['before'], created['after'])
        self.assertEqual(rejected['after'], created['after'])


if __name__ == '__main__':
    unittest.main()
