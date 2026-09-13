from __future__ import annotations

import unittest

from tibber_heatpump_bridge.sensors import (
    DigitalPotentiometer,
    KtySensor,
    NtcSensor,
    Pt1000Sensor,
    ResistorLadder,
    ShuntEmulator,
    ShuntObservation,
    coverage_c,
    emulate,
    fake_temperature,
    fit_shunt,
    identify_sensor,
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


# Resistance values printed in the Tecalor TTF / TTF cool installation manual,
# section "Fühler Widerstandswerte". The AFS 2 outdoor sensor supplied with the
# unit is one of these two characteristics; which one is settled by measuring.
TECALOR_TABLE = {
    # °C: (PT1000 Ω, KTY Ω)
    -30: (882, 1250),
    -20: (922, 1367),
    -10: (961, 1495),
    0: (1000, 1630),
    10: (1039, 1772),
    20: (1078, 1922),
    25: (1097, 2000),
    30: (1117, 2080),
    40: (1155, 2245),
    50: (1194, 2417),
    60: (1232, 2597),
    70: (1271, 2785),
    80: (1309, 2980),
    90: (1347, 3182),
    100: (1385, 3392),
}


class TecalorSensorTableTests(unittest.TestCase):
    def test_pt1000_matches_the_manual(self):
        sensor = Pt1000Sensor()
        for temp_c, (pt1000, _kty) in TECALOR_TABLE.items():
            self.assertAlmostEqual(sensor.resistance(temp_c), pt1000, delta=1.0, msg=f"{temp_c} °C")

    def test_kty_matches_the_manual(self):
        sensor = KtySensor()
        for temp_c, (_pt1000, kty) in TECALOR_TABLE.items():
            self.assertAlmostEqual(sensor.resistance(temp_c), kty, delta=4.0, msg=f"{temp_c} °C")

    def test_kty_round_trips(self):
        sensor = KtySensor()
        for temp_c in (-25.0, -5.0, 12.5, 33.0):
            self.assertAlmostEqual(sensor.temperature(sensor.resistance(temp_c)), temp_c, places=4)

    def test_make_sensor_knows_kty(self):
        self.assertIsInstance(make_sensor("kty"), KtySensor)

    def test_the_two_characteristics_are_far_apart(self):
        """One measurement settles which sensor the AFS 2 is: at any plausible
        outdoor temperature the two characteristics differ by hundreds of ohms."""
        pt, kty = Pt1000Sensor(), KtySensor()
        for temp_c in (-10.0, 0.0, 10.0, 20.0):
            self.assertGreater(kty.resistance(temp_c) - pt.resistance(temp_c), 400.0)


class ResistorLadderTests(unittest.TestCase):
    """Option B in docs/virtual-outdoor-sensor.md: a fixed base resistor plus
    binary-weighted resistors, each shorted by a latching relay. Needed for
    PT1000/KTY, whose span is too narrow for a digital potentiometer."""

    def _ladder(self) -> ResistorLadder:
        return ResistorLadder(base_ohms=850.0, steps=(1, 2, 4, 8, 16, 32, 64, 128, 256))

    def test_span_and_step(self):
        ladder = self._ladder()
        self.assertEqual(ladder.taps, 512)
        self.assertAlmostEqual(ladder.resistance_at(0), 850.0)
        self.assertAlmostEqual(ladder.resistance_at(511), 1361.0)

    def test_code_is_the_binary_sum(self):
        ladder = self._ladder()
        self.assertAlmostEqual(ladder.resistance_at(0b101), 850.0 + 1 + 4)
        self.assertEqual(ladder.tap_for(850.0 + 37.0), 37)

    def test_relays_in_circuit(self):
        ladder = self._ladder()
        self.assertEqual(ladder.relays_for(0b000001011), (True, True, False, True) + (False,) * 5)

    def test_clamps_outside_its_range(self):
        ladder = self._ladder()
        self.assertEqual(ladder.tap_for(10.0), 0)
        self.assertEqual(ladder.tap_for(99_999.0), 511)

    def test_covers_the_pt1000_range_needed_for_the_hague(self):
        ladder, sensor = self._ladder(), Pt1000Sensor()
        low, high = coverage_c(sensor, ladder)
        self.assertLessEqual(low, -19.0)
        self.assertGreaterEqual(high, 35.0)

    def test_resolution_is_better_than_half_a_kelvin(self):
        ladder, sensor = self._ladder(), Pt1000Sensor()
        for temp_c in (-19.0, 0.0, 20.0):
            self.assertLess(resolution_k(sensor, ladder, temp_c), 0.5)

    def test_emulate_works_against_a_ladder(self):
        ladder, sensor = self._ladder(), Pt1000Sensor()
        result = emulate(sensor, ladder, -19.0)
        self.assertLess(abs(result.error_k), 0.3)
        self.assertEqual(ladder.resistance_at(result.tap), result.achieved_ohms)


class ShuntEmulatorTests(unittest.TestCase):
    """Parallel digital rheostat across the real AFS 2, with a small series bias."""

    def _rig(self) -> ShuntEmulator:
        return ShuntEmulator(
            sensor=Pt1000Sensor(),
            pot=DigitalPotentiometer(full_scale_ohms=100_000.0, taps=1024, wiper_ohms=35.0),
            bias_ohms=39.0,
        )

    def test_open_rheostat_presents_the_bias_warmer(self):
        """With the shunt open only the series bias acts, so the pump reads warm."""
        rig = self._rig()
        self.assertLess(rig.shift_k(0.0, rig.pot.taps - 1), -6.0)

    def test_never_presents_outside_the_safe_window(self):
        rig = self._rig()
        for real_c in (-19.0, 0.0, 10.0):
            lowest, highest = rig.safe_taps(real_c)
            self.assertGreaterEqual(rig.presented_c(real_c, lowest), rig.min_present_c - 0.5)
            self.assertLessEqual(rig.presented_c(real_c, highest), rig.max_present_c + 0.5)
            # the tap below the safe floor would short the sensor
            if lowest > 0:
                self.assertLess(rig.presented_c(real_c, lowest - 1), rig.min_present_c)

    def test_a_requested_shift_is_clamped_not_obeyed_blindly(self):
        rig = self._rig()
        tap = rig.tap_for_shift(0.0, 60.0)
        self.assertGreaterEqual(rig.presented_c(0.0, tap), rig.min_present_c - 0.5)

    def test_closing_the_rheostat_makes_it_look_colder(self):
        rig = self._rig()
        shifts = [rig.shift_k(0.0, tap) for tap in (1023, 700, 400, 200)]
        self.assertEqual(shifts, sorted(shifts), "shift must increase as the shunt closes")

    def test_reaches_both_directions_across_the_heating_range(self):
        rig = self._rig()
        for real_c in (-19.0, -10.0, 0.0, 10.0):
            low, high = rig.shift_range_k(real_c)
            self.assertLess(low, -4.0, f"cannot pretend it is milder at {real_c}")
            self.assertGreater(high, 5.0, f"cannot pretend it is colder at {real_c}")

    def test_tap_for_shift_round_trips(self):
        rig = self._rig()
        for real_c in (-19.0, -5.0, 0.0, 8.0):
            for want in (-4.0, -2.0, 0.0, 2.0, 4.0, 6.0):
                tap = rig.tap_for_shift(real_c, want)
                self.assertAlmostEqual(rig.shift_k(real_c, tap), want, delta=0.1)

    def test_resolution_is_far_finer_than_a_ladder(self):
        rig = self._rig()
        for want in (-4.0, 0.0, 4.0):
            tap = rig.tap_for_shift(0.0, want)
            neighbour = rig.shift_k(0.0, tap + 1)
            self.assertLess(abs(neighbour - rig.shift_k(0.0, tap)), 0.1)

    def test_recovers_the_true_outdoor_temperature_from_the_pumps_reading(self):
        """The pump reports 0.1 C resolution on register 506; inverting the
        shunt must give back the real value, so no second sensor is needed."""
        rig = self._rig()
        for real_c in (-19.0, -10.0, 2.5, 12.0):
            tap = rig.tap_for_shift(real_c, 3.0)
            reported = round(rig.presented_c(real_c, tap), 1)
            self.assertAlmostEqual(rig.recover_real_c(reported, tap), real_c, delta=0.1)

    def test_part_tolerance_costs_only_a_fraction_of_the_shift(self):
        """A 1 % rheostat error costs ~0.13 K on a 4 K shift -- an order below
        what a series ladder's contact resistance would cost, and a fixed gain
        error that can be calibrated out by measuring the part once and
        entering the measured value as ``full_scale_ohms``."""
        nominal = self._rig()
        skewed = ShuntEmulator(
            sensor=Pt1000Sensor(),
            pot=DigitalPotentiometer(full_scale_ohms=101_000.0, taps=1024, wiper_ohms=35.0),
            bias_ohms=39.0,
        )
        tap = nominal.tap_for_shift(0.0, 4.0)
        self.assertLess(abs(skewed.shift_k(0.0, tap) - nominal.shift_k(0.0, tap)), 0.2)


class SelfCalibrationTests(unittest.TestCase):
    """The circuit identifies its own sensor and calibrates its own parts from
    the pump's outdoor register -- no multimeter, no assumed tolerances."""

    def _truth(self, sensor, bias=39.0, scale=100_000.0) -> ShuntEmulator:
        return ShuntEmulator(
            sensor=sensor,
            pot=DigitalPotentiometer(full_scale_ohms=scale, taps=1024, wiper_ohms=35.0),
            bias_ohms=bias,
        )

    def _observe(self, truth, weather, taps, quantise=0.1):
        obs = []
        for real_c, tap in zip(weather, taps, strict=True):
            obs.append(
                ShuntObservation(
                    bypass_c=round(real_c, 1),
                    tap=tap,
                    emulated_c=round(round(truth.presented_c(real_c, tap) / quantise) * quantise, 3),
                )
            )
        return obs

    def test_identifies_pt1000(self):
        truth = self._truth(Pt1000Sensor())
        obs = self._observe(truth, [5.0, 5.0, -2.0, 11.0], [300, 500, 350, 420])
        result = identify_sensor(obs)
        self.assertEqual(result.kind, "pt1000")
        self.assertTrue(result.confident, f"margin {result.margin_k}")

    def test_identifies_kty(self):
        truth = self._truth(KtySensor(), bias=130.0)
        obs = self._observe(truth, [5.0, 5.0, -2.0, 11.0], [300, 500, 350, 420])
        result = identify_sensor(obs)
        self.assertEqual(result.kind, "kty")
        self.assertTrue(result.confident, f"margin {result.margin_k}")

    def test_fitting_needs_more_observations_than_free_parameters(self):
        """Two fitted part values cost two degrees of freedom, so one or two
        observations cannot separate the candidates -- refuse rather than
        return a confident-looking guess."""
        truth = self._truth(Pt1000Sensor())
        for count in (1, 2):
            obs = self._observe(truth, [5.0, 5.0][:count], [300, 500][:count])
            with self.assertRaises(ValueError):
                identify_sensor(obs)

    def test_a_single_tap_change_separates_them_against_nominal_parts(self):
        """Without fitting, one tap change is already decisive in the field:
        the two characteristics predict readings kelvins apart, against a
        register quantised to 0.1 C."""
        pt = self._truth(Pt1000Sensor(), bias=39.0)
        kty = self._truth(KtySensor(), bias=39.0)
        tap = pt.pot.tap_for(20_000.0)
        self.assertGreater(abs(pt.presented_c(5.0, tap) - kty.presented_c(5.0, tap)), 3.0)

    def test_fit_recovers_part_values_the_datasheet_only_bounds(self):
        """A +1 % rheostat and a bias resistor 4 % high must both come back."""
        truth = self._truth(Pt1000Sensor(), bias=40.6, scale=101_000.0)
        obs = self._observe(truth, [6.0, 1.0, -4.0, 9.0, 12.0], [280, 360, 480, 620, 800])
        fitted, error = fit_shunt(obs, Pt1000Sensor())
        self.assertLess(error, 0.15)
        self.assertAlmostEqual(fitted.bias_ohms, 40.6, delta=4.0)
        self.assertAlmostEqual(fitted.pot.full_scale_ohms, 101_000.0, delta=4_000.0)

    def test_calibration_beats_trusting_the_datasheet(self):
        """The whole point: a calibrated build predicts the pump better than a
        nominal one, so the 1 % tolerance stops costing accuracy."""
        truth = self._truth(Pt1000Sensor(), bias=40.6, scale=101_000.0)
        obs = self._observe(truth, [6.0, 1.0, -4.0, 9.0, 12.0], [280, 360, 480, 620, 800])
        nominal = self._truth(Pt1000Sensor())
        fitted, _ = fit_shunt(obs, Pt1000Sensor())
        check = self._observe(truth, [3.0, -8.0, 14.0], [330, 540, 700])
        nominal_err = max(abs(nominal.presented_c(o.bypass_c, o.tap) - o.emulated_c) for o in check)
        fitted_err = max(abs(fitted.presented_c(o.bypass_c, o.tap) - o.emulated_c) for o in check)
        self.assertLess(fitted_err, nominal_err)
        self.assertLess(fitted_err, 0.15)

    def test_identification_needs_two_candidates(self):
        truth = self._truth(Pt1000Sensor())
        obs = self._observe(truth, [5.0], [300])
        with self.assertRaises(ValueError):
            identify_sensor(obs, candidates={"pt1000": Pt1000Sensor()})
