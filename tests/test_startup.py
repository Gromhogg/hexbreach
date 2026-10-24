"""The starting-up popup: the game's line to it (startup.py), run.sh, and the
popup's own reading of that line (splash/hexbreach-splash, if it is built)."""
import os
import subprocess
import sys
import tempfile
import time
import unittest

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main  # noqa: E402
import scenes  # noqa: E402
import startup  # noqa: E402
import ui  # noqa: E402

SPLASH = os.path.join(ROOT, "splash", "hexbreach-splash")


class StartupTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(startup.connect)        # with the variable gone again: back to no popup
        self.addCleanup(os.environ.pop, "HEXBREACH_SPLASH_FD", None)

    def attach(self):
        """Connect startup to a new pipe. Returns the end the popup would read."""
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        os.set_blocking(r, False)
        os.environ["HEXBREACH_SPLASH_FD"] = str(w)
        startup.connect()
        self.assertEqual(startup._fd, w)
        return r

    def lines(self, r):
        """What has been written to the pipe, and whether its far end is now closed."""
        data = b""
        try:
            while True:
                chunk = os.read(r, 65536)
                if not chunk:
                    return data.decode().splitlines(), True
                data += chunk
        except BlockingIOError:
            return data.decode().splitlines(), False

    def test_nothing_without_a_popup(self):
        startup.connect()
        self.assertIsNone(startup._fd)
        startup.step(20, "loading engine")
        startup.done()

    def test_lines_reach_the_popup(self):
        r = self.attach()
        startup.step(20, "loading engine")
        startup.step(55, "opening display")
        self.assertEqual(self.lines(r), (["20 loading engine", "55 opening display"], False))
        startup.done()
        self.assertEqual(self.lines(r), (["done"], True))
        self.assertNotIn("HEXBREACH_SPLASH_FD", os.environ)
        # the pipe's number is free for the next file opened: nothing more may be written to it
        with tempfile.TemporaryFile() as fh:
            startup.step(99, "late")
            startup.done()
            self.assertEqual(os.fstat(fh.fileno()).st_size, 0)

    def test_a_popup_that_has_gone(self):
        r, w = os.pipe()
        os.environ["HEXBREACH_SPLASH_FD"] = str(w)
        startup.connect()
        os.close(r)
        startup.step(20, "loading engine")      # no error, and no more tries
        self.assertIsNone(startup._fd)
        startup.done()

    def test_a_popup_that_has_stopped_reading(self):
        r = self.attach()
        try:
            while True:
                os.write(startup._fd, b"x" * 4096)
        except BlockingIOError:
            pass
        began = time.monotonic()
        startup.step(20, "loading engine")
        self.assertLess(time.monotonic() - began, 0.5)
        self.assertIsNotNone(startup._fd)       # still there: the next line may get through

    def test_a_variable_that_names_no_pipe(self):
        with tempfile.TemporaryFile() as fh:
            for value in ("", "pipe", "1", "9999", str(fh.fileno())):
                os.environ["HEXBREACH_SPLASH_FD"] = value
                startup.connect()
                self.assertIsNone(startup._fd, value)
                startup.step(20, "loading engine")
                startup.done()
            self.assertEqual(os.fstat(fh.fileno()).st_size, 0)

    def test_the_game_reports_its_start(self):
        r = self.attach()
        with tempfile.TemporaryDirectory(prefix="hexbreach-startup-") as tmp:
            game = main.Game(save_path=os.path.join(tmp, "save.json"), captures_dir=tmp)
            self.assertIsInstance(game.scene, scenes.TitleScene)
            lines, closed = self.lines(r)
            self.assertEqual(lines[-1], "95 drawing title")
            self.assertFalse(closed)                        # not done until a frame is up
            game.loop(max_frames=1, fixed_dt=0.05)
            self.assertIsInstance(game.scene, scenes.TitleScene)
        self.assertEqual(self.lines(r), (["done"], True))
        percents = [int(line.split()[0]) for line in lines]
        self.assertEqual(percents, sorted(percents))        # the bar never has to go back

    def test_fullscreen_ends_the_popup_before_the_switch(self):
        r = self.attach()
        with tempfile.TemporaryDirectory(prefix="hexbreach-startup-") as tmp:
            game = main.Game(save_path=os.path.join(tmp, "save.json"), captures_dir=tmp, fullscreen=True)
            self.addCleanup(game.set_fullscreen, False, remember=False)
            lines, closed = self.lines(r)
            self.assertEqual(lines[-1], "done")
            self.assertTrue(closed)
            self.assertNotIn("95 drawing title", lines)
            game.loop(max_frames=1, fixed_dt=0.05)
            self.assertIsInstance(game.scene, scenes.TitleScene)

    def test_run_sh_is_sound(self):
        self.assertEqual(subprocess.run(["bash", "-n", os.path.join(ROOT, "run.sh")]).returncode, 0)

    def test_the_popup_looks_like_the_game(self):
        with open(os.path.join(ROOT, "splash", "splash.swift")) as fh:
            source = fh.read()
        for name in ("BLACK", "GREEN", "DIM", "AMBER", "RED"):
            self.assertIn("let %s = rgb(%d, %d, %d)" % ((name,) + getattr(ui, name)), source)
        self.assertIn('"%s %s\\r\\n"' % (scenes.TITLE, scenes.VERSION), source)

    @unittest.skipUnless(os.access(SPLASH, os.X_OK), "the popup has not been built")
    def test_the_popup_reads_the_line(self):
        said = "20 loading engine\nnoise\n55 opening display\ndone\n"
        out = subprocess.run([SPLASH, "check"], input=said, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout.splitlines(), ["20 loading engine", "55 opening display", "done"])
        # the pipe closing with no "done" is a start that failed
        out = subprocess.run([SPLASH, "check"], input="20 loading engine\n", capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)


if __name__ == "__main__":
    unittest.main()
