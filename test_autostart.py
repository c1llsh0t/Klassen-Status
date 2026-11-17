"""Tests für autostart.py (laufen unter Linux und macOS mit einem Test-Ordner)."""

import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import autostart


class AutostartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Alles in einen Test-Ordner umleiten, damit wir nichts Echtes ändern
        self.env = mock.patch.dict(os.environ, {"HOME": self.tmp.name,
                                                "XDG_CONFIG_HOME": self.tmp.name + "/.config"})
        self.env.start()
        self.home = mock.patch.object(Path, "home", return_value=Path(self.tmp.name))
        self.home.start()

    def tearDown(self):
        self.home.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_einstellungen_speichern_und_laden(self):
        self.assertEqual(autostart.load_settings(), {})
        autostart.save_settings({"name": "Lena", "role": "student"})
        self.assertEqual(autostart.load_settings()["name"], "Lena")

    @unittest.skipIf(autostart.SYSTEM == "Windows", "Linux-Test")
    def test_linux_autostart_an_und_aus(self):
        with mock.patch.object(autostart, "SYSTEM", "Linux"):
            self.assertFalse(autostart.is_enabled())
            self.assertIsNone(autostart.set_enabled(True))
            self.assertTrue(autostart.is_enabled())
            text = autostart._linux_file().read_text(encoding="utf-8")
            self.assertIn("Exec=", text)
            self.assertIn("--autostart", text)
            autostart.set_enabled(False)
            self.assertFalse(autostart.is_enabled())

    def test_mac_plist(self):
        data = plistlib.loads(autostart.mac_plist(["/Applications/Klassenzimmer.app/x", "--autostart"]))
        self.assertTrue(data["RunAtLoad"])
        self.assertEqual(data["ProgramArguments"][-1], "--autostart")

    def test_pfad_mit_leerzeichen(self):
        line = autostart.linux_desktop(["/home/lena/Meine Apps/Klassenzimmer", "--autostart"])
        self.assertIn('Exec="/home/lena/Meine Apps/Klassenzimmer" --autostart', line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
