from __future__ import annotations

import unittest

from tibber_heatpump_bridge.sensors import (
    DigitalPotentiometer,
    NtcSensor,
    Pt1000Sensor,
    coverage_c,
    emulate,
    fake_temperature,
    make_sensor,
    resolution_k,
)


class NtcTests(unittest.TestCase):
    def test_nominal_point_and_monotonic(self):
        ntc = NtcSensor()
        self.assertAlmostEqual(ntc.resistance(25.0), 10000.0, places=6)
        self.assertGreater(ntc.resistance(0.0), ntc.resistance(10.0))
        self.assertGreater(ntc.resistance(-20.0), 90000.0)

    def test_roundtrip(self):
        ntc = NtcSensor(r25=10000.0, beta=3977.0)
        for temp in (-25.0, -5.0, 0.0, 7.5, 25.0, 40.0):
            self.assertAlmostEqual(ntc.temperature(ntc.resistance(temp)), temp, places=6)

    def test_rejects_non_positive_resistance(self):
        with self.assertRaises(ValueError):
            NtcSensor().temperature(0.0)


class Pt1000Tests(unittest.TestCase):
    def test_reference_points(self):
        pt = Pt1000Sensor()
        self.assertAlmostEqual(pt.resistance(0.0), 1000.0, places=6)
        self.assertAlmostEqual(pt.resistance(100.0), 1385.055, places=2)
        self.assertAlmostEqual(pt.resistance(-20.0), 921.6, delta=0.2)

    def test_roundtrip_including_negative(self):
        pt = Pt1000Sensor()
        for temp in (-30.0, -10.0, 0.0, 12.3, 35.0):
            self.assertAlmostEqual(pt.temperature(pt.resistance(temp)), temp, places=5)


class PotentiometerTests(unittest.TestCase):
    def test_ntc_with_100k_1024_tap_pot(self):
        ntc = NtcSensor()
        pot = DigitalPotentiometer(full_scale_ohms=100_000.0, taps=1024, wiper_ohms=35.0)
        emu = emulate(ntc, pot, -3.0)
        self.assertLess(abs(emu.error_k), 0.1)
        self.assertEqual(emu.tap, pot.tap_for(ntc.resistance(-3.0)))
        self.assertLess(resolution_k(ntc, pot, 0.0), 0.1)
        self.assertLess(resolution_k(ntc, pot, 25.0), 0.4)
        # One 100 kOhm pot only reaches about -19 C with a 10 kOhm NTC; colder
        # climates need a switched series resistor or a second pot in series.
        low, high = coverage_c(ntc, pot)
        self.assertAlmostEqual(low, -18.9, delta=0.2)
        self.assertGreater(high, 40.0)
        wide = DigitalPotentiometer(full_scale_ohms=200_000.0, taps=2048, wiper_ohms=70.0)
        self.assertLess(coverage_c(ntc, wide)[0], -29.0)

    def test_pt1000_needs_series_resistor_and_fine_pot(self):
        pt = Pt1000Sensor()
        coarse = DigitalPotentiometer(full_scale_ohms=20_000.0, taps=1024)
        self.assertGreater(resolution_k(pt, coarse, 0.0), 3.0)  # 19.5 ohm steps are useless
        fine = DigitalPotentiometer(full_scale_ohms=1_000.0, taps=1024, series_ohms=850.0)
        self.assertLess(resolution_k(pt, fine, 0.0), 0.3)
        emu = emulate(pt, fine, -7.0)
        self.assertLess(abs(emu.error_k), 0.2)

    def test_clamping(self):
        pot = DigitalPotentiometer(full_scale_ohms=100.0, taps=11)
        self.assertEqual(pot.tap_for(-5.0), 0)
        self.assertEqual(pot.tap_for(500.0), 10)
        self.assertEqual(pot.resistance_at(99), 100.0)


class HelpersTests(unittest.TestCase):
    def test_make_sensor(self):
        self.assertIsInstance(make_sensor("NTC", r25=4700.0), NtcSensor)
        self.assertIsInstance(make_sensor("pt1000"), Pt1000Sensor)
        with self.assertRaises(ValueError):
            make_sensor("thermocouple")

    def test_fake_temperature_sign(self):
        # Positive shift = pretend it is colder = more heat.
        self.assertEqual(fake_temperature(2.0, 3.0), -1.0)
        self.assertEqual(fake_temperature(2.0, -6.0), 8.0)


if __name__ == "__main__":
    unittest.main()
