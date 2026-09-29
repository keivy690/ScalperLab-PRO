import subprocess
import unittest
from unittest.mock import patch

from scalperlab.clock_monitor import ClockValidationMonitor, inspect_mt5_clock
from scalperlab.system_clock import (CLOCK_MONITOR_RETRY_SECONDS,
                                    MAX_CLOCK_CHECK_AGE_SECONDS,
                                    SystemClockService)


TERMINAL_ID = "terminal-demo"
ACCOUNT = "123456@Broker-Demo"


def valid_probe():
    return {
        "ok": True,
        "severity": "ok",
        "source": "time.example.test",
        "ntp_offset_seconds": 0.2,
        "service_running": True,
        "startup_type": "Auto",
        "mt5_status": "verified",
        "mt5_symbols_checked": 1,
        "mt5_symbols_total": 1,
        "mt5_server_utc_offset_seconds": 10_800,
        "mt5_detail": "Tick recente confirmou UTC.",
        "terminal_id": TERMINAL_ID,
        "account_fingerprint": ACCOUNT,
        "symbols": ["EURUSD#"],
    }


def verified_clock():
    clock = SystemClockService()
    clock._set_state(
        status="system_synchronized",
        checked_at="2026-09-25T12:00:00+00:00",
        mt5_terminal_id=TERMINAL_ID,
        mt5_account_fingerprint=ACCOUNT,
    )
    clock.set_mt5_result(
        verified=True,
        detail="Tick recente confirmou UTC.",
        symbols_checked=1,
        symbols_total=1,
        server_utc_offset_seconds=10_800,
        terminal_id=TERMINAL_ID,
        account_fingerprint=ACCOUNT,
        symbols=["EURUSD#"],
    )
    return clock


class ClockValidationMonitorTests(unittest.TestCase):
    def test_start_preflight_confirms_healthy_clock_without_repair(self):
        clock = SystemClockService()
        healthy = {"ok": True, "source": "time.example.test",
                   "ntp_offset_seconds": 0.1, "service_running": True,
                   "startup_type": "Auto"}
        with patch.object(clock, "_inspect", return_value=healthy), \
             patch.object(clock, "_repair") as repair:
            result = clock.verify_read_only()
        self.assertEqual(result["status"], "system_synchronized")
        repair.assert_not_called()

    def test_start_preflight_does_not_repair_unhealthy_clock(self):
        clock = SystemClockService()
        unhealthy = {"ok": False, "detail": "Desvio UTC acima do limite",
                     "source": "time.example.test", "service_running": True,
                     "startup_type": "Auto"}
        with patch.object(clock, "_inspect", return_value=unhealthy), \
             patch.object(clock, "_repair") as repair:
            result = clock.verify_read_only()
        self.assertEqual(result["status"], "error")
        self.assertIn("Desvio UTC", result["detail"])
        repair.assert_not_called()

    def test_periodic_success_renews_proof_and_reports_recovery(self):
        now = [1_000.0]
        with patch("scalperlab.system_clock.time.monotonic", side_effect=lambda: now[0]):
            clock = verified_clock()
            now[0] += 300
            events = []
            monitor = ClockValidationMonitor(
                clock, valid_probe,
                on_event=lambda level, detail: events.append((level, detail)),
            )

            clock.apply_periodic_result({
                "ok": False, "severity": "transient", "detail": "NTP temporariamente indisponível",
            })
            result = monitor.run_once()
            snapshot = clock.snapshot()

        self.assertTrue(result["applied"])
        self.assertEqual(result["status"], "synchronized")
        self.assertEqual(snapshot["proof_age_seconds"], 0.0)
        self.assertEqual(snapshot["monitor_status"], "healthy")
        self.assertEqual(events[0][0], "INFO")
        self.assertIn("revalidado", events[0][1])

    def test_transient_failure_keeps_unexpired_proof_then_expires_it(self):
        now = [1_000.0]
        with patch("scalperlab.system_clock.time.monotonic", side_effect=lambda: now[0]):
            clock = verified_clock()
            now[0] += 120
            transient = {"ok": False, "severity": "transient", "detail": "NTP indisponível"}
            first = clock.apply_periodic_result(transient)
            still_valid = clock.snapshot()

            now[0] += MAX_CLOCK_CHECK_AGE_SECONDS
            second = clock.apply_periodic_result(transient)
            expired = clock.snapshot()

        self.assertEqual(first["status"], "synchronized")
        self.assertEqual(still_valid["monitor_status"], "retrying")
        self.assertEqual(first["next_delay_seconds"], CLOCK_MONITOR_RETRY_SECONDS)
        self.assertEqual(second["status"], "expired")
        self.assertEqual(expired["status"], "expired")

    def test_hard_failure_blocks_until_a_fresh_valid_probe_recovers(self):
        now = [2_000.0]
        with patch("scalperlab.system_clock.time.monotonic", side_effect=lambda: now[0]):
            clock = verified_clock()
            now[0] += 30
            blocked = clock.apply_periodic_result({
                "ok": False, "severity": "hard", "detail": "Desvio UTC acima do limite",
            })
            retry = clock.apply_periodic_result({
                "ok": False, "severity": "transient", "detail": "NTP sem resposta",
            })
            recovered = clock.apply_periodic_result(valid_probe())
            final = clock.snapshot()

        self.assertEqual(blocked["status"], "error")
        self.assertEqual(retry["status"], "expired")
        self.assertEqual(recovered["status"], "synchronized")
        self.assertEqual(recovered["event"], "recovered")
        self.assertEqual(final["mt5_account_fingerprint"], ACCOUNT)

    def test_identity_change_invalidates_monitor_and_old_proof(self):
        clock = verified_clock()
        result = clock.apply_periodic_result({
            "ok": False, "invalidate": True, "detail": "A conta mudou.",
        })

        self.assertEqual(result["status"], "not_checked")
        self.assertFalse(clock.monitor_should_run())
        self.assertIsNone(clock.snapshot()["proof_age_seconds"])

    def test_expiry_uses_monotonic_age_not_wall_clock_timestamp(self):
        now = [10.0]
        with patch("scalperlab.system_clock.time.monotonic", side_effect=lambda: now[0]):
            clock = verified_clock()
            with clock._lock:
                clock._state["checked_at"] = "2000-01-01T00:00:00+00:00"
            self.assertTrue(clock.is_currently_verified(
                terminal_id=TERMINAL_ID, account_fingerprint=ACCOUNT,
            ))
            now[0] += MAX_CLOCK_CHECK_AGE_SECONDS + 1
        self.assertFalse(clock.is_currently_verified(
            terminal_id=TERMINAL_ID, account_fingerprint=ACCOUNT,
        ))

    def test_time_source_falls_back_to_read_only_windows_status(self):
        clock = SystemClockService()
        denied = subprocess.CompletedProcess(
            ["w32tm", "/query", "/source"], 1, "", "Acesso negado. (0x80070005)",
        )
        status = subprocess.CompletedProcess(
            ["w32tm", "/query", "/status"], 0,
            "Indicador de Salto: 0\nFonte: time.windows.com,0x9\n", "",
        )
        with patch.object(clock, "_run", side_effect=[denied, status]):
            source, error = clock._time_source()

        self.assertEqual(source, "time.windows.com,0x9")
        self.assertIsNone(error)


class MT5ClockProbeTests(unittest.TestCase):
    @staticmethod
    def tick(age=0.5, offset=10_800, residual=0.2, basis="UTC"):
        return {
            "ok": True,
            "time_normalization": {
                "basis": basis,
                "age_seconds": age,
                "server_utc_offset_seconds": offset,
                "calibration_residual_seconds": residual,
            },
        }

    def test_one_fresh_tick_is_enough_and_stale_market_symbols_are_ignored(self):
        class Gateway:
            def current_tick(self, symbol):
                return (MT5ClockProbeTests.tick() if symbol == "EURUSD#"
                        else MT5ClockProbeTests.tick(age=900))

        result = inspect_mt5_clock(
            Gateway(), ["EURUSD#", "CLOSED-MARKET"],
            terminal_id=TERMINAL_ID, account_fingerprint=ACCOUNT,
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mt5_symbols_checked"], 1)
        self.assertEqual(result["mt5_symbols_total"], 2)
        self.assertEqual(result["symbols"], ["EURUSD#"])

    def test_no_recent_tick_is_transient_not_a_clock_divergence(self):
        class Gateway:
            def current_tick(self, _symbol):
                return MT5ClockProbeTests.tick(age=900)

        result = inspect_mt5_clock(
            Gateway(), ["CLOSED-MARKET"],
            terminal_id=TERMINAL_ID, account_fingerprint=ACCOUNT,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["severity"], "transient")

    def test_conflicting_fresh_server_offsets_are_hard_failure(self):
        class Gateway:
            def current_tick(self, symbol):
                offset = 10_800 if symbol == "EURUSD#" else 0
                return MT5ClockProbeTests.tick(offset=offset)

        result = inspect_mt5_clock(
            Gateway(), ["EURUSD#", "XAUUSD#"],
            terminal_id=TERMINAL_ID, account_fingerprint=ACCOUNT,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["severity"], "hard")
        self.assertIn("mudou durante a coleta", result["detail"])

    def test_invalid_future_tick_is_hard_failure(self):
        class Gateway:
            def current_tick(self, _symbol):
                return MT5ClockProbeTests.tick(age=-8)

        result = inspect_mt5_clock(
            Gateway(), ["EURUSD#"],
            terminal_id=TERMINAL_ID, account_fingerprint=ACCOUNT,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["severity"], "hard")


if __name__ == "__main__":
    unittest.main()
