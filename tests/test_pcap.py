"""sources.py: the pcap / pcapng readers and the LIVE source."""
import os
import random
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import packets  # noqa: E402
import sources  # noqa: E402


def sample_frames(n_flows=12, seed=1):
    rng, syn, frames = random.Random(seed), sources.SynthSource(), []
    for i in range(n_flows):
        frames += syn.flow(rng, 1 + i % 5)
    return frames


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hexbreach-test-")
        self.frames = sample_frames()

    def path(self, name):
        return os.path.join(self.dir, name)

    def test_pcap_round_trip(self):
        for name, kw in (("le.pcap", {}), ("be.pcap", {"endian": ">"}), ("ns.pcap", {"nanos": True}),
                         ("be_ns.pcap", {"endian": ">", "nanos": True})):
            sources.write_pcap(self.path(name), self.frames, **kw)
            got = sources.read_capture(self.path(name))
            self.assertEqual([f for _, f, _ in got], self.frames, name)
            self.assertTrue(all(lt == packets.LINKTYPE_ETHERNET for lt, _, _ in got))

    def test_pcapng_round_trip(self):
        for name, endian in (("le.pcapng", "<"), ("be.pcapng", ">")):
            sources.write_pcapng(self.path(name), self.frames, endian=endian)
            got = sources.read_capture(self.path(name))
            self.assertEqual([f for _, f, _ in got], self.frames, name)
            self.assertEqual([orig for _, _, orig in got], [len(f) for f in self.frames])

    def test_pcapng_skips_unknown_blocks_and_tracks_interfaces(self):
        def block(btype, body):
            body += b"\x00" * (-len(body) % 4)
            return struct.pack("<II", btype, len(body) + 12) + body + struct.pack("<I", len(body) + 12)

        ip = self.frames[0][14:]
        data = block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
        data += block(1, struct.pack("<HHI", packets.LINKTYPE_ETHERNET, 0, 0))
        data += block(1, struct.pack("<HHI", packets.LINKTYPE_RAW, 0, 0))
        data += block(5, b"\x00" * 12)                                # interface statistics: ignored
        data += block(6, struct.pack("<IIIII", 0, 0, 0, len(self.frames[0]), len(self.frames[0])) + self.frames[0])
        data += block(0xBAD, b"junk")
        data += block(6, struct.pack("<IIIII", 1, 0, 0, len(ip), len(ip)) + ip)
        data += block(6, struct.pack("<IIIII", 7, 0, 0, 4, 4) + b"abcd")   # unknown interface: dropped
        got = sources.read_pcapng(data)
        self.assertEqual([(lt, f) for lt, f, _ in got],
                         [(packets.LINKTYPE_ETHERNET, self.frames[0]), (packets.LINKTYPE_RAW, ip)])
        self.assertTrue(packets.parse(got[1][1], got[1][0]).has("IPv4"))

    def test_truncated_files_keep_what_they_can(self):
        sources.write_pcap(self.path("a.pcap"), self.frames)
        sources.write_pcapng(self.path("a.pcapng"), self.frames)
        for name in ("a.pcap", "a.pcapng"):
            with open(self.path(name), "rb") as fh:
                data = fh.read()
            with open(self.path("cut_" + name), "wb") as fh:
                fh.write(data[:len(data) - 7])
            got = sources.read_capture(self.path("cut_" + name))
            self.assertEqual([f for _, f, _ in got], self.frames[:-1], name)

    def test_not_a_capture(self):
        with open(self.path("notes.pcap"), "wb") as fh:
            fh.write(b"this is not a capture file at all")
        with self.assertRaises(sources.CaptureError):
            sources.read_capture(self.path("notes.pcap"))
        with open(self.path("empty.pcap"), "wb"):
            pass
        with self.assertRaises(sources.CaptureError):
            sources.read_capture(self.path("empty.pcap"))


class PcapSourceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hexbreach-test-")

    def test_loads_both_formats_and_reports_bad_files(self):
        frames = sample_frames(20)
        half = len(frames) // 2
        sources.write_pcap(os.path.join(self.dir, "one.pcap"), frames[:half])
        sources.write_pcapng(os.path.join(self.dir, "two.pcapng"), frames[half:])
        with open(os.path.join(self.dir, "broken.pcap"), "wb") as fh:
            fh.write(b"nope")
        with open(os.path.join(self.dir, "readme.txt"), "w") as fh:
            fh.write("ignored")
        src = sources.PcapSource(self.dir)
        self.assertEqual(src.files, ["one.pcap", "two.pcapng"])
        self.assertEqual(len(src.errors), 1)
        self.assertIn("broken.pcap", src.errors[0])
        self.assertEqual(len(src.packets), len(frames))
        self.assertFalse(src.using_fallback)

        rng = random.Random(0)
        real = {f for f in frames}
        for _ in range(50):
            self.assertIn(src.packet(rng, 3).raw, real)
        self.assertTrue(src.packet(rng, 1, need=("IPv4", "TCP")).has("TCP"))
        buf = src.buffer(300, rng)
        self.assertEqual(len(buf), 300)
        self.assertIn(bytes(buf[:14]), {f[:14] for f in frames})

    def test_node_names_come_from_the_capture(self):
        frames = sample_frames(20)
        sources.write_pcap(os.path.join(self.dir, "c.pcap"), frames)
        src = sources.PcapSource(self.dir)
        seen = set()
        for f in frames:
            i = packets.parse(f).info
            seen |= {"%s:%d" % (i["src_ip"], i["sport"]), "%s:%d" % (i["dst_ip"], i["dport"])}
        rng = random.Random(0)
        for _ in range(100):
            self.assertIn(src.node_name(rng), seen)

    def test_falls_back_when_too_few_usable_packets(self):
        arp = packets.build_ethernet("ff:ff:ff:ff:ff:ff", "3c:22:fb:00:00:01", packets.ETH_ARP, bytes(28))
        sources.write_pcap(os.path.join(self.dir, "thin.pcap"), sample_frames(1)[:3] + [arp] * 40)
        src = sources.PcapSource(self.dir)
        self.assertEqual(len(src.packets), 3)          # ARP has no IP header: not usable
        self.assertTrue(src.using_fallback)
        rng = random.Random(0)
        self.assertTrue(src.packet(rng, 1, need=("IPv4",)).has("IPv4"))
        self.assertEqual(len(src.buffer(128, rng)), 128)
        self.assertIn("synthesized", src.describe())

    def test_empty_or_missing_directory(self):
        for directory in (self.dir, os.path.join(self.dir, "does-not-exist")):
            src = sources.PcapSource(directory)
            self.assertTrue(src.using_fallback)
            self.assertIsNotNone(src.packet(random.Random(0)))
            self.assertIn("empty", src.describe())

    def test_requirement_the_capture_cannot_meet_uses_synth(self):
        rng = random.Random(0)
        syn = sources.SynthSource()
        udp_only = [syn.make("udp", rng) for _ in range(30)]
        sources.write_pcap(os.path.join(self.dir, "udp.pcap"), udp_only)
        src = sources.PcapSource(self.dir)
        self.assertFalse(src.using_fallback)
        self.assertTrue(src.packet(rng, 1, need=("IPv4", "TCP")).has("TCP"))
        self.assertIn(src.packet(rng, 1, need=("UDP",)).raw, set(udp_only))


if __name__ == "__main__":
    unittest.main()
