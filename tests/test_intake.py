import unittest

from diplomacy.intake import parse_key_text


PADDED = """
Questão 1                Questão 2
C    E    E    C    E    C    X    E    0    0    0    0

0    0    0    0
"""

GLUED = """
Questão 26              Questão28            Questão 30
C    E    E    C    E    C    X    E    C    E    E    C
"""

SHORT = """
Questão 1
C E
"""


class KeyGridTests(unittest.TestCase):
    def test_trailing_pad_cells_are_ignored(self):
        cells = parse_key_text(PADDED)
        self.assertEqual(list(cells), ["1.1", "1.2", "1.3", "1.4", "2.1", "2.2", "2.3", "2.4"])
        self.assertEqual(cells["2.3"]["value"], "X")

    def test_heading_without_space_still_groups_four_cells(self):
        cells = parse_key_text(GLUED)
        self.assertEqual(set(cells), {f"{number}.{item}" for number in (26, 28, 30) for item in range(1, 5)})

    def test_short_row_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            parse_key_text(SHORT)


if __name__ == "__main__":
    unittest.main()
