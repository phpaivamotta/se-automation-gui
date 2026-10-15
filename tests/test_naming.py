import tempfile
import unittest
from pathlib import Path

from se_automation import naming


class DetectJobTests(unittest.TestCase):
    def check(self, path, job, root_name):
        info = naming.detect_job(Path(path))
        self.assertIsNotNone(info, path)
        self.assertEqual(info.job_number, job)
        self.assertEqual(info.job_root.name, root_name)

    def test_standard(self):
        self.check(r"F:\MAS\Jobs\20274080\Working Drawings", "20274080", "20274080")

    def test_suffix(self):
        self.check(r"F:\MAS\Jobs\20223006-C\Working Drawings", "20223006-C", "20223006-C")
        self.check(r"F:\MAS\Jobs\CARGILL\20233160-1\Working Drawings", "20233160-1", "20233160-1")

    def test_folder_with_customer_name(self):
        self.check(r"F:\MAS\Jobs\20263756, Coogee\Working Drawings", "20263756", "20263756, Coogee")
        self.check(r"F:\MAS\Jobs\Oxy\20233308, Technip\Working Drawings", "20233308", "20233308, Technip")

    def test_nested_drawings_folder(self):
        self.check(r"F:\MAS\Jobs\20274080\Working Drawings\Area 2\New folder", "20274080", "20274080")

    def test_no_job(self):
        self.assertIsNone(naming.detect_job(Path(r"C:\Users\someone\Desktop\stuff")))


class PrefixAndNameTests(unittest.TestCase):
    def test_default_prefix(self):
        self.assertEqual(naming.default_prefix("20274080"), "4080")
        self.assertEqual(naming.default_prefix("20223006-C"), "3006-C")
        self.assertEqual(naming.default_prefix("20263767-1"), "3767-1")
        self.assertEqual(naming.default_prefix("abc"), "")

    def test_format(self):
        self.assertEqual(naming.format_name("4080", 103, "P10-8"), "4080-0103-P10-8")
        self.assertEqual(naming.format_name("3006-C", 301, "P10-2"), "3006-C-0301-P10-2")

    def test_parse(self):
        p = naming.parse_name("4080-0103-P10-8")
        self.assertEqual((p.prefix, p.number, p.description), ("4080", 103, "P10-8"))
        p = naming.parse_name("3006-C-0301-P10-2")
        self.assertEqual((p.prefix, p.number, p.description), ("3006-C", 301, "P10-2"))
        p = naming.parse_name("3243-2-150C-0301-S2-1.5")
        self.assertEqual((p.prefix, p.number, p.description), ("3243-2-150C", 301, "S2-1.5"))
        self.assertIsNone(naming.parse_name("P10-8"))
        self.assertIsNone(naming.parse_name("New folder"))

    def test_parse_with_hint(self):
        p = naming.parse_name("1234-5678-0101-D6-36", prefix_hint="1234-5678")
        self.assertEqual((p.prefix, p.number, p.description), ("1234-5678", 101, "D6-36"))

    def test_drawing_number(self):
        self.assertEqual(naming.drawing_number_from_name("3006-C-0301-P10-2"), "0301")
        self.assertIsNone(naming.drawing_number_from_name("P10-8"))

    def test_parse_number(self):
        self.assertEqual(naming.parse_number("0201"), 201)
        self.assertEqual(naming.parse_number("140"), 140)
        self.assertIsNone(naming.parse_number("0"))
        self.assertIsNone(naming.parse_number("12a"))

    def test_validate(self):
        self.assertIsNone(naming.validate_name_part("P10-8 (9.5 OD)", "x"))
        self.assertIsNotNone(naming.validate_name_part("P10/8", "x"))
        self.assertIsNotNone(naming.validate_name_part("", "x"))
        self.assertIsNotNone(naming.validate_name_part("P10-8.", "x"))


class GuessDescriptionTests(unittest.TestCase):
    def make(self, folder, dft, asms=()):
        root = Path(self.tmp.name) / folder
        root.mkdir(parents=True)
        for a in asms:
            (root / f"{a}.asm").touch()
        path = root / f"{dft}.dft"
        path.touch()
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_template(self):
        self.assertEqual(naming.guess_description(self.make("P10-8", "P10-8", ["P10-8"])), "P10-8")

    def test_previous_job(self):
        path = self.make("3621-0101-S2-1", "3621-0101-S2-1", ["S2-1"])
        self.assertEqual(naming.guess_description(path), "S2-1")

    def test_previous_job_without_assembly_hint(self):
        self.assertEqual(naming.guess_description(self.make("x", "3621-0101-S2-1")), "S2-1")

    def test_old_suffix_convention_uses_assembly(self):
        path = self.make("3006-0301-C-P10-2", "3006-0301-C-P10-2", ["P10-2", "Guide Angle Assy_Type 5"])
        self.assertEqual(naming.guess_description(path), "P10-2")


if __name__ == "__main__":
    unittest.main()
