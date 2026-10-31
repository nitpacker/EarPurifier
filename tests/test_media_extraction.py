import os
import sys
import unittest
from unittest.mock import patch, MagicMock

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from media_engine import extract_audio, MediaEngineError, JobAbortedError


class TestMediaExtraction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = os.path.join(root_dir, ".test_temp_extraction")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.dummy_media = os.path.join(self.temp_dir, "input.mp4")
        with open(self.dummy_media, "wb") as f:
            f.write(b"dummy media content")
        self.output_flac = os.path.join(self.temp_dir, "output.flac")

    def tearDown(self):
        for f in [self.dummy_media, self.output_flac]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        if os.path.exists(self.temp_dir):
            try:
                os.rmdir(self.temp_dir)
            except OSError:
                pass

    @patch("media_engine.DependencyManager.get_executable", return_value="ffmpeg.exe")
    @patch("media_engine._run_ffmpeg_abortable")
    def test_extract_audio_enforces_16bit_stereo_48khz_invariants(self, mock_run, mock_dep):
        """Verify extract_audio strictly enforces -sample_fmt s16, -c:a flac, -ar 48000, -ac 2."""
        result = extract_audio(self.dummy_media, self.output_flac, stream_index=1)
        self.assertEqual(result, self.output_flac)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        # Verify exact invariant tokens
        self.assertIn("-c:a", cmd)
        flac_idx = cmd.index("-c:a")
        self.assertEqual(cmd[flac_idx + 1], "flac")

        self.assertIn("-sample_fmt", cmd)
        s16_idx = cmd.index("-sample_fmt")
        self.assertEqual(cmd[s16_idx + 1], "s16")

        self.assertIn("-ar", cmd)
        ar_idx = cmd.index("-ar")
        self.assertEqual(cmd[ar_idx + 1], "48000")

        self.assertIn("-ac", cmd)
        ac_idx = cmd.index("-ac")
        self.assertEqual(cmd[ac_idx + 1], "2")

        # Verify correct stream mapping
        self.assertIn("-map", cmd)
        map_idx = cmd.index("-map")
        self.assertEqual(cmd[map_idx + 1], "0:a:1")

    def test_extract_audio_nonexistent_file_raises(self):
        """Verify extract_audio raises FileNotFoundError for missing media."""
        with self.assertRaises(FileNotFoundError):
            extract_audio("nonexistent_file.mkv", self.output_flac)

    @patch("media_engine.DependencyManager.get_executable", return_value="ffmpeg.exe")
    @patch("media_engine._run_ffmpeg_abortable", side_effect=JobAbortedError("Aborted"))
    def test_extract_audio_aborted_cleans_partial_file(self, mock_run, mock_dep):
        """Verify aborted extraction removes any partially created output file."""
        with open(self.output_flac, "wb") as f:
            f.write(b"partial flac")
        self.assertTrue(os.path.exists(self.output_flac))

        with self.assertRaises(JobAbortedError):
            extract_audio(self.dummy_media, self.output_flac)

        self.assertFalse(os.path.exists(self.output_flac))


if __name__ == "__main__":
    unittest.main()
