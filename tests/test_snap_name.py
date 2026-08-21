"""Pulling an OCR'd channel name back to the one the chart printed.

  python3 -m unittest tests.test_snap_name

Two properties matter and they pull against each other. A mangled treatment
channel must be recovered, or it reaches the CSV as its own column and no
downstream mapping will ever claim it. And an ADDITIVE's product code must
never be dragged onto a treatment channel, which would be a mislabel rather
than a repair — so the additive tests below are the important half.

The comparison is done in one case. It used to title-case the OCR'd name and
match it against the printed list, which is not all title case: "GORV
Pressure" could not be reached by any variant of itself.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lib1


class SnapName(unittest.TestCase):
    def test_a_dropped_letter_is_recovered(self):
        self.assertEqual(lib1._snap_name("Slurry ate"), "Slurry Rate")
        self.assertEqual(lib1._snap_name("Treatin Pressure"), "Treating Pressure")
        self.assertEqual(lib1._snap_name("Backside Pressue"), "Backside Pressure")

    def test_more_than_one_dropped_letter(self):
        # these two came back as their own channels on three pages of 00915
        self.assertEqual(lib1._snap_name("Slur ate"), "Slurry Rate")
        self.assertEqual(lib1._snap_name("§lurr ate"), "Slurry Rate")

    def test_the_one_entry_that_is_not_title_case(self):
        # titling the input put "Gorv Pressure" against "GORV Pressure" and
        # scored nothing, so no misread of this channel could ever be repaired
        self.assertEqual(lib1._snap_name("en GORV Pressure"), "GORV Pressure")
        self.assertEqual(lib1._snap_name("GORV Pressue"), "GORV Pressure")

    def test_bottomhole_and_wellhead_are_never_guessed_between(self):
        # OCR drops the first letter of "BH Prop Conc" and what is left sits
        # exactly as close to "WH Prop Conc". They are different
        # measurements; refusing is the only honest answer.
        self.assertEqual(lib1._snap_name("H Prop Conc"), "H Prop Conc")

    def test_names_that_are_already_right_are_untouched(self):
        for n in ("Treating Pressure", "Slurry Rate", "Prop Conc",
                  "BH Prop Conc", "Btm Prop Conc", "GORV Pressure"):
            self.assertEqual(lib1._snap_name(n), n)

    def test_an_additive_code_is_never_pulled_onto_a_treatment_channel(self):
        # the property the cutoff exists for
        for n in ("B702 CONC", "475 CONC", "AQUGAR CONC", "XE363 CONC",
                  "J475 CONC", "B665 conc", "CONC 475", "Aqucar Conc"):
            self.assertEqual(lib1._snap_name(n), n)

    def test_something_far_from_every_printed_name_is_left_alone(self):
        self.assertEqual(lib1._snap_name("Prop Bint Con Sn"), "Prop Bint Con Sn")
        self.assertEqual(lib1._snap_name("Monitor Pressure"), "Monitor Pressure")

    def test_a_name_with_no_letters_at_all(self):
        self.assertEqual(lib1._snap_name("475"), "475")
        self.assertEqual(lib1._snap_name(""), "")


if __name__ == "__main__":
    unittest.main()
