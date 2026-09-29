import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from scalperlab.db import Database
from scalperlab.replay import (MIN_VALIDATION_BARS, ReplayValidationError,
                               run_pullback_replay, run_pullback_validation)


def _bars(count=65, *, spread=1):
    start = 1_700_000_000
    return [{"time": start + index * 300, "open": 1.0, "high": 1.01,
             "low": 0.999, "close": 1.001, "spread": spread,
             "tick_volume": 100, "real_volume": 0}
            for index in range(count)]


def _contract(**updates):
    return {"point": 0.0001, "trade_tick_size": 0.0001,
            "trade_tick_value_profit": 1.0, "trade_tick_value_loss": 1.0,
            "volume_min": 0.01, "volume_step": 0.01, "chart_mode": 0,
            **updates}


def _eligible(*_args, **_kwargs):
    return {"decision": {"order_eligible": True, "side": "BUY",
                         "stop": 0.995, "target": 1.01}}


class ReplayTests(unittest.TestCase):
    def test_actual_baseline_crossing_calculates_atr(self):
        from scalperlab.replay import _momentum_baseline_decision
        bars = _bars(65)
        bars[-2]['close'] = .999
        bars[-1]['close'] = 1.002
        result = _momentum_baseline_decision(bars, _contract(), .0001)
        self.assertTrue(result['decision']['order_eligible'])
        self.assertEqual(result['decision']['side'], 'BUY')

    def test_requires_explicit_cost_confirmation(self):
        with self.assertRaisesRegex(ReplayValidationError, "Confirme"):
            run_pullback_replay(symbol="EURUSD#", timeframe="M5", bars=_bars(),
                                contract=_contract())

    def test_same_bar_stop_and_target_use_adverse_stop_first(self):
        bars = _bars()
        bars[60].update({"open": 1.0, "high": 1.02, "low": 0.99, "close": 1.005})
        seen_windows = []

        def eligible(symbol, timeframe, window, *_args, **_kwargs):
            seen_windows.append((len(window), window[-1]["time"]))
            return _eligible()

        with patch("scalperlab.replay.analyze_market", side_effect=eligible):
            report = run_pullback_replay(symbol="EURUSD#", timeframe="M5", bars=bars,
                                         contract=_contract(), costs_confirmed=True)
        self.assertGreaterEqual(report["metrics"]["same_bar_stop_first_cases"], 1)
        self.assertEqual(report["trades"][0]["exit_reason"],
                         "stop_loss_ambos_no_mesmo_candle_stop_primeiro")
        self.assertEqual(seen_windows[0], (60, bars[59]["time"]))
        self.assertLess(report["trades"][0]["net_r"], 0)

    def test_rejects_last_price_charts_and_invalid_ohlc(self):
        with self.assertRaisesRegex(ReplayValidationError, "preços Bid"):
            run_pullback_replay(symbol="US30Cash#", timeframe="M5", bars=_bars(),
                                contract=_contract(chart_mode=1), costs_confirmed=True)
        bars = _bars()
        bars[5]["high"] = 0.9
        with self.assertRaisesRegex(ReplayValidationError, "inconsistente"):
            run_pullback_replay(symbol="EURUSD#", timeframe="M5", bars=bars,
                                contract=_contract(), costs_confirmed=True)

    def test_requires_market_compatible_volume_cap(self):
        with self.assertRaisesRegex(ReplayValidationError, "0,01 lote"):
            run_pullback_replay(symbol="EURUSD#", timeframe="M5", bars=_bars(),
                                contract=_contract(volume_min=0.1), costs_confirmed=True)

    def test_replay_snapshot_and_result_are_retained_together(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "replay.sqlite3")
            report = run_pullback_replay(symbol="EURUSD#", timeframe="M5", bars=_bars(),
                                         contract=_contract(), costs_confirmed=True)
            db.save_replay_run(run_id="run-1", terminal_id="demo-terminal",
                               account_fingerprint_sha256="a" * 64,
                               symbol="EURUSD#", timeframe="M5",
                               data_sha256=report["data_sha256"],
                               parameters=report["parameters"], result=report,
                               dataset={"bars": _bars(), "contract": _contract()})
            saved = db.get_replay_run("run-1")
            self.assertEqual(saved["result"]["data_sha256"], report["data_sha256"])
            self.assertEqual(len(saved["dataset"]["bars"]), len(_bars()))
            self.assertEqual(db.list_replay_runs()[0]["run_id"], "run-1")

    def test_validation_rejects_history_too_short_for_chronological_holdout(self):
        with self.assertRaisesRegex(ReplayValidationError, "pelo menos 200"):
            run_pullback_validation(symbol="EURUSD#", timeframe="M5", bars=_bars(199),
                                    contract=_contract(), costs_confirmed=True)

    def test_validation_separates_final_holdout_and_compares_same_management(self):
        bars = _bars(MIN_VALIDATION_BARS)
        with patch("scalperlab.replay.analyze_market", side_effect=_eligible), \
                patch("scalperlab.replay._momentum_baseline_decision", side_effect=_eligible):
            report = run_pullback_validation(
                symbol="EURUSD#", timeframe="M5", bars=bars, contract=_contract(),
                costs_confirmed=True)

        split = int(len(bars) * 0.70)
        self.assertEqual(report["segments"]["development"]["bars"], split)
        self.assertEqual(report["segments"]["holdout"]["bars"], len(bars) - split)
        self.assertEqual(report["segments"]["holdout"]["start_utc"],
                         report["segments"]["holdout"]["pullback"]["trades"][0]["signal_time_utc"])
        self.assertTrue(report["comparison"]["shared_exit_and_cost_assumptions"])
        self.assertEqual(report["comparison"]["sample_status"],
                         "amostra_descritiva_minima_atingida")
        self.assertAlmostEqual(report["comparison"]["holdout_delta_net_r"], 0.0)
        self.assertEqual(report["status"], "triagem_ohlc_holdout_nao_homologado")
        self.assertEqual(report["data_quality"]["timestamp_basis"],
                         "UTC informado pela API Python oficial do MetaTrader 5")


if __name__ == "__main__":
    unittest.main()
