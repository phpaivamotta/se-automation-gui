"""Renumbering/insert logic, run against temporary folders with a fake Design Manager."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from se_automation import jobfolder, operations as ops
from se_automation.plan import Row, build_plan
from se_automation.titleblock import DRAWING_NUMBER


class QuietReporter(ops.PrintReporter):
    def __init__(self):
        self.messages = []

    def log(self, message, level="info"):
        self.messages.append((level, message))


def fake_copier(source_dft: Path, dest: Path) -> Path:
    """Stands in for Design Manager: copies the draft and its assembly."""
    for f in source_dft.parent.iterdir():
        if f.suffix.lower() in (".dft", ".asm") and (f.suffix.lower() == ".asm" or f == source_dft):
            shutil.copy2(f, dest / f.name)
    return dest / source_dft.name


class RecordingWriter:
    def __init__(self):
        self.calls = []

    def write(self, dft, values, leave_open):
        self.calls.append((dft.name, dict(values)))
        return []


class JobTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.wd = base / "20274080" / "Working Drawings"
        self.wd.mkdir(parents=True)
        self.templates = base / "Templates"
        for code in ("D6-36", "P10-8", "P20-20", "S2-1"):
            folder = self.templates / code.split("-")[0] / code
            folder.mkdir(parents=True)
            (folder / f"{code}.dft").write_text(code)
            (folder / f"{code}.asm").write_text(code)

    def tearDown(self):
        self.tmp.cleanup()

    def template(self, code):
        return self.templates / code.split("-")[0] / code / f"{code}.dft"

    def existing(self, name, dft_name=None):
        folder = self.wd / name
        folder.mkdir()
        (folder / f"{dft_name or name}.dft").write_text(name)
        (folder / f"{name.split('-', 2)[2]}.asm").write_text(name)

    def rows_from_disk(self):
        scan = jobfolder.scan_drawings_folder(self.wd, "4080")
        return [Row(d.description, existing=d) for d in scan.drawings], scan

    def apply(self, rows, start=101, prefix="4080", writer=None, open_docs=()):
        scan = jobfolder.scan_drawings_folder(self.wd, prefix)
        plan = build_plan(self.wd, rows, prefix, start, scan.ignored)
        self.assertTrue(plan.ok, plan.errors)
        writer = writer or RecordingWriter()
        result = ops.apply_plan(plan, copier=fake_copier, writer=writer,
                                title_values={("Custom", "CLIENT"): "ACME"}, fill_title_block=True,
                                leave_new_open=False, open_documents=lambda: list(open_docs),
                                pdf_folders=[self.wd.parent / "Submittal" / "Fab Latest Revision"],
                                reporter=QuietReporter())
        return plan, result, writer

    def on_disk(self):
        out = []
        for folder in sorted(p for p in self.wd.iterdir() if p.is_dir()):
            out.append((folder.name, sorted(f.name for f in folder.glob("*.dft"))))
        return out


class InsertAndRenumberTests(JobTestCase):
    def test_new_job(self):
        rows = [Row(c, source_dft=self.template(c), source_label=c) for c in ("D6-36", "P10-8", "P20-20")]
        _, result, writer = self.apply(rows)
        self.assertEqual(self.on_disk(), [
            ("4080-0101-D6-36", ["4080-0101-D6-36.dft"]),
            ("4080-0102-P10-8", ["4080-0102-P10-8.dft"]),
            ("4080-0103-P20-20", ["4080-0103-P20-20.dft"]),
        ])
        self.assertEqual(writer.calls[0], ("4080-0101-D6-36.dft",
                                           {("Custom", "CLIENT"): "ACME", DRAWING_NUMBER: "0101"}))
        self.assertEqual(result.failed, [])

    def test_insert_pushes_following_drawings_down(self):
        """The example from the request: a 2nd P10-8 right after the first one."""
        for name in ("4080-0101-D6-36", "4080-0102-P10-8", "4080-0103-P20-20"):
            self.existing(name)
        pdf_dir = self.wd.parent / "Submittal" / "Fab Latest Revision"
        pdf_dir.mkdir(parents=True)
        (pdf_dir / "4080-0103-P20-20.pdf").touch()

        rows, _ = self.rows_from_disk()
        rows.insert(2, Row("P10-8", source_dft=self.template("P10-8"), source_label="template"))
        plan, result, writer = self.apply(rows)

        self.assertEqual([p.status for p in plan.items][:3], ["no change", "no change", "NEW - template"])
        self.assertEqual(self.on_disk(), [
            ("4080-0101-D6-36", ["4080-0101-D6-36.dft"]),
            ("4080-0102-P10-8", ["4080-0102-P10-8.dft"]),
            ("4080-0103-P10-8", ["4080-0103-P10-8.dft"]),
            ("4080-0104-P20-20", ["4080-0104-P20-20.dft"]),
        ])
        self.assertEqual(result.renamed, [("4080-0103-P20-20", "4080-0104-P20-20")])
        self.assertEqual([p.name for p in result.stale_pdfs], ["4080-0103-P20-20.pdf"])
        # Renumbered drawing only gets its drawing number; the new one gets the title block.
        self.assertIn(("4080-0104-P20-20.dft", {DRAWING_NUMBER: "0104"}), writer.calls)
        self.assertIn(("4080-0103-P10-8.dft", {("Custom", "CLIENT"): "ACME", DRAWING_NUMBER: "0103"}),
                      writer.calls)
        # The assembly keeps its template name.
        self.assertTrue((self.wd / "4080-0104-P20-20" / "P20-20.asm").exists())

    def test_reorder_swaps_without_collisions(self):
        for name in ("4080-0101-A-1", "4080-0102-B-2", "4080-0103-C-3"):
            self.existing(name)
        rows, _ = self.rows_from_disk()
        rows.reverse()
        self.apply(rows)
        self.assertEqual([n for n, _ in self.on_disk()], ["4080-0101-C-3", "4080-0102-B-2", "4080-0103-A-1"])

    def test_custom_start_number_and_prefix(self):
        rows = [Row("S2-1", source_dft=self.template("S2-1"))]
        self.apply(rows, start=140, prefix="3006-C")
        self.assertEqual(self.on_disk(), [("3006-C-0140-S2-1", ["3006-C-0140-S2-1.dft"])])

    def test_fixes_draft_left_with_template_name(self):
        self.existing("4080-0101-D6-36", dft_name="D6-36")
        rows, _ = self.rows_from_disk()
        plan, _, _ = self.apply(rows)
        self.assertEqual(plan.items[0].status, "fix draft name")
        self.assertEqual(self.on_disk(), [("4080-0101-D6-36", ["4080-0101-D6-36.dft"])])

    def test_gap_is_closed(self):
        self.existing("4080-0101-D6-36")
        self.existing("4080-0103-P20-20")
        rows, _ = self.rows_from_disk()
        self.apply(rows)
        self.assertEqual([n for n, _ in self.on_disk()], ["4080-0101-D6-36", "4080-0102-P20-20"])

    def test_refuses_when_drawing_is_open_in_solid_edge(self):
        for name in ("4080-0101-D6-36", "4080-0102-P20-20"):
            self.existing(name)
        rows, _ = self.rows_from_disk()
        rows.insert(0, Row("S2-1", source_dft=self.template("S2-1")))
        open_doc = str(self.wd / "4080-0102-P20-20" / "4080-0102-P20-20.dft")
        with self.assertRaises(RuntimeError):
            self.apply(rows, open_docs=[open_doc])
        self.assertEqual([n for n, _ in self.on_disk()], ["4080-0101-D6-36", "4080-0102-P20-20"])


class RollbackTests(JobTestCase):
    def test_failed_rename_restores_everything(self):
        for name in ("4080-0101-A-1", "4080-0102-B-2", "4080-0103-C-3"):
            self.existing(name)
        before = self.on_disk()
        rows, _ = self.rows_from_disk()
        rows.reverse()
        plan = build_plan(self.wd, rows, "4080", 101)

        real_rename = os.rename

        def flaky(src, dst):
            # C-3 has already been moved into 0101 when A-1 can't be moved into 0103.
            if Path(dst).name == "4080-0103-A-1":
                raise PermissionError("locked")
            return real_rename(src, dst)

        with mock.patch("se_automation.operations.os.rename", side_effect=flaky), \
                mock.patch("se_automation.operations.time.sleep"):
            with self.assertRaises(PermissionError):
                ops.rename_existing(plan, QuietReporter())
        self.assertEqual(self.on_disk(), before)


class PlanValidationTests(JobTestCase):
    def test_duplicate_names_are_errors(self):
        rows = [Row("P10-8", source_dft=self.template("P10-8")), Row("P10-8", source_dft=self.template("P10-8"))]
        plan = build_plan(self.wd, rows, "4080", 101)
        self.assertTrue(plan.ok)   # different numbers, so different names
        plan = build_plan(self.wd, [rows[0]], "", 101)
        self.assertFalse(plan.ok)

    def test_unrecognised_folder_blocks_its_name(self):
        rows = [Row("P10-8", source_dft=self.template("P10-8"))]
        plan = build_plan(self.wd, rows, "4080", 101, ignored_folders=["4080-0101-P10-8"])
        self.assertFalse(plan.ok)

    def test_bad_description(self):
        plan = build_plan(self.wd, [Row("P10/8", source_dft=self.template("P10-8"))], "4080", 101)
        self.assertFalse(plan.ok)

    def test_missing_source(self):
        plan = build_plan(self.wd, [Row("P10-8", source_dft=self.wd / "nope.dft")], "4080", 101)
        self.assertFalse(plan.ok)

    def test_scan_ignores_non_drawing_folders(self):
        self.existing("4080-0101-D6-36")
        (self.wd / "Old stuff").mkdir()
        (self.wd / "4080-0102-EMPTY-1").mkdir()
        scan = jobfolder.scan_drawings_folder(self.wd)
        self.assertEqual([d.folder.name for d in scan.drawings], ["4080-0101-D6-36"])
        self.assertEqual(sorted(scan.ignored), ["4080-0102-EMPTY-1", "Old stuff"])
        self.assertEqual(scan.common_prefix, "4080")
        self.assertEqual(scan.first_number, 101)


if __name__ == "__main__":
    unittest.main()
