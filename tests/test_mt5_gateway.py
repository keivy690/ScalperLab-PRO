import threading
import time
import unittest
from datetime import timezone
from types import SimpleNamespace

from scalperlab.mt5_gateway import MT5Gateway


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_RETURN = 2
    SYMBOL_TRADE_MODE_FULL = 4
    SYMBOL_ORDER_MARKET = 1
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    SYMBOL_TRADE_EXECUTION_MARKET = 2

    def __init__(self, mode=0):
        self.mode = mode
        self.positions = [SimpleNamespace(ticket=12, symbol="EURUSD", type=0, volume=0.1,
                                          price_open=1.08, price_current=1.081, sl=0.0,
                                          tp=0.0, profit=1.0, time=1, magic=5, comment="")]
        self.sent = 0
        self.requests = []
        self.initialize_count = 0
        self.account_login = 42
        self.account_server = "Demo"
        self.pending_orders = []
        self.historical_orders = []
        self.historical_deals = []
        self.history_query_bounds = None
        self.order_check_hook = None
        self.test_symbol = SimpleNamespace(name="EURUSD#", trade_mode=4, order_mode=127,
                                           volume_min=0.01, filling_mode=2)
        self.visible_symbols = [self.test_symbol, SimpleNamespace(name="HK50Cash#", visible=True)]

    def initialize(self, **_kwargs):
        self.initialize_count += 1
        return True
    def shutdown(self): pass
    def last_error(self): return (0, "ok")
    def account_info(self):
        return SimpleNamespace(login=self.account_login, server=self.account_server, company="Broker", currency="USD",
                               balance=1000.0, equity=1001.0, profit=1.0,
                               trade_mode=self.mode, leverage=100, trade_allowed=True, trade_expert=True,
                               margin=0.0, margin_free=1000.0, margin_level=0.0,
                               limit_orders=0, fifo_close=False, server_time=1)
    def terminal_info(self): return SimpleNamespace(connected=True, name="MetaTrader 5", build=1, trade_allowed=True)
    def positions_get(self, ticket=None, symbol=None):
        rows = list(self.positions)
        if ticket is not None:
            rows = [position for position in rows if position.ticket == ticket]
        if symbol is not None:
            rows = [position for position in rows if position.symbol == symbol]
        return rows
    def orders_get(self): return list(self.pending_orders)
    def history_orders_get(self, start, end):
        self.history_query_bounds = (start, end)
        return list(self.historical_orders)
    def history_deals_get(self, start, end):
        self.history_query_bounds = (start, end)
        return list(self.historical_deals)
    def order_calc_profit(self, *_args): return -1.0
    def order_calc_margin(self, *_args): return 10.0
    def symbol_info_tick(self, _symbol): return SimpleNamespace(ask=1.082, bid=1.081)
    def symbol_info(self, _symbol): return SimpleNamespace(filling_mode=2)
    def symbols_get(self, group=None): return self.visible_symbols
    def order_check(self, _request):
        if self.order_check_hook:
            self.order_check_hook()
        return SimpleNamespace(retcode=0)
    def order_send(self, request):
        self.sent += 1
        self.requests.append(dict(request))
        if request.get("magic") == 209221001 and request["action"] == self.TRADE_ACTION_DEAL and request.get("position") is None:
            self.positions.append(SimpleNamespace(ticket=99, symbol=request["symbol"], type=0, volume=request["volume"],
                                                  price_open=request["price"], price_current=request["price"], sl=0,
                                                  tp=0, profit=0, time=1, magic=request["magic"], comment=request["comment"]))
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=99, deal=100)
        if request.get("magic", 0) >= 209221050 and request.get("position") is None:
            self.positions.append(SimpleNamespace(ticket=200 + self.sent, symbol=request["symbol"], type=request["type"],
                                                  volume=request["volume"], price_open=request.get("price", 1.082),
                                                  price_current=request.get("price", 1.082), sl=request["sl"],
                                                  tp=request["tp"], profit=0, time=1, magic=request["magic"],
                                                  comment=request["comment"]))
            return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=200 + self.sent, deal=300 + self.sent)
        self.positions = [position for position in self.positions if position.ticket != request["position"]]
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=22, deal=23)


class MT5GatewayTests(unittest.TestCase):
    def test_history_queries_use_utc_and_serialize_order_and_deal_fields(self):
        mt5 = FakeMT5()
        mt5.historical_orders = [SimpleNamespace(ticket=71, time_setup=100, time_done=101,
                                                 type=0, state=4, magic=5, position_id=70,
                                                 symbol="EURUSD#", volume_initial=0.01,
                                                 volume_current=0.0, price_open=1.1,
                                                 comment="SC0123456789 entry")]
        mt5.historical_deals = [SimpleNamespace(ticket=72, order=71, time=101, time_msc=101000,
                                                type=0, entry=0, magic=5, position_id=70,
                                                volume=0.01, price=1.1, commission=-0.1,
                                                swap=0.0, profit=0.0, fee=0.0,
                                                symbol="EURUSD#", comment="SC0123456789 entry")]
        gateway = MT5Gateway(mt5)
        orders = gateway.history_orders("2026-09-24T12:00:00Z", "2026-09-24T12:01:00Z")
        start, end = mt5.history_query_bounds
        self.assertTrue(orders["available"])
        self.assertEqual(orders["items"][0]["ticket"], 71)
        self.assertEqual(start.tzinfo, timezone.utc)
        self.assertEqual(end.tzinfo, timezone.utc)
        deals = gateway.history_deals("2026-09-24T12:00:00+00:00", "2026-09-24T12:01:00+00:00")
        self.assertTrue(deals["available"])
        self.assertEqual(deals["items"][0]["commission"], -0.1)

    def test_history_query_refuses_invalid_or_unbounded_interval(self):
        gateway = MT5Gateway(FakeMT5())
        result = gateway.history_orders("2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z")
        self.assertFalse(result["available"])
        self.assertEqual(result["items"], [])

    def test_real_account_never_arms_demo_or_submits_order(self):
        mt5 = FakeMT5(mode=2)
        gateway = MT5Gateway(mt5)
        result = gateway.arm_demo("ATIVAR SOMENTE DEMO")
        self.assertFalse(result["ok"])
        self.assertFalse(gateway.demo_armed)
        stopped = gateway.emergency_stop_demo("FECHAR TODAS AS POSIÇÕES DEMO")
        self.assertTrue(stopped["blocked"])
        self.assertEqual(mt5.sent, 0)

    def test_market_symbol_validation_requires_exact_visible_broker_name(self):
        gateway = MT5Gateway(FakeMT5())
        exact = gateway.validate_market_symbols(["EURUSD#"])
        self.assertTrue(exact["available"])
        self.assertTrue(exact["valid"])
        unresolved = gateway.validate_market_symbols(["EURUSD"])
        self.assertFalse(unresolved["valid"])
        self.assertEqual(unresolved["invalid"][0]["suggestions"], ["EURUSD#"])
        mixed_case = gateway.validate_market_symbols(["HK50Cash#"])
        self.assertTrue(mixed_case["valid"])
        wrong_case = gateway.validate_market_symbols(["HK50CASH#"])
        self.assertFalse(wrong_case["valid"])
        self.assertEqual(wrong_case["invalid"][0]["suggestions"], ["HK50Cash#"])

    def test_demo_close_requires_arm_and_reconciles_position(self):
        mt5 = FakeMT5()
        gateway = MT5Gateway(mt5)
        blocked = gateway.close_demo_position(12, "FECHAR POSIÇÃO DEMO")
        self.assertFalse(blocked["ok"])
        self.assertEqual(mt5.sent, 0)
        self.assertTrue(gateway.arm_demo("ATIVAR SOMENTE DEMO")["ok"])
        closed = gateway.close_demo_position(12, "FECHAR POSIÇÃO DEMO")
        self.assertTrue(closed["ok"])
        self.assertEqual(mt5.sent, 1)

    def test_demo_close_arm_is_bound_to_account_identity(self):
        mt5 = FakeMT5()
        gateway = MT5Gateway(mt5)
        self.assertTrue(gateway.arm_demo("ATIVAR SOMENTE DEMO")["ok"])
        mt5.account_login = 43
        result = gateway.close_demo_position(12, "FECHAR POSIÇÃO DEMO")
        self.assertFalse(result["ok"])
        self.assertFalse(gateway.demo_armed)
        self.assertEqual(mt5.sent, 0)

    def test_demo_smoke_order_opens_and_reconciles_close(self):
        mt5 = FakeMT5()
        mt5.positions = []
        mt5.symbol_info_tick = lambda _symbol: SimpleNamespace(ask=1.1, bid=1.0999)
        gateway = MT5Gateway(mt5)
        result = gateway.place_demo_smoke_order("ENVIAR TESTE DEMO")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["volume"], 0.01)
        self.assertEqual(mt5.sent, 2)
        self.assertEqual(mt5.positions, [])

    def test_demo_smoke_order_refuses_to_touch_existing_positions(self):
        mt5 = FakeMT5()
        gateway = MT5Gateway(mt5)
        result = gateway.place_demo_smoke_order("ENVIAR TESTE DEMO")
        self.assertFalse(result["ok"])
        self.assertEqual(mt5.sent, 0)

    def test_demo_smoke_order_refuses_to_touch_pending_orders(self):
        mt5 = FakeMT5()
        mt5.positions = []
        mt5.pending_orders = [SimpleNamespace(ticket=13)]
        result = MT5Gateway(mt5).place_demo_smoke_order("ENVIAR TESTE DEMO")
        self.assertFalse(result["ok"])
        self.assertEqual(mt5.sent, 0)

    def test_demo_smoke_order_check_rejection_never_sends(self):
        mt5 = FakeMT5()
        mt5.positions = []
        mt5.order_check = lambda _request: SimpleNamespace(retcode=10013)
        result = MT5Gateway(mt5).place_demo_smoke_order("ENVIAR TESTE DEMO")
        self.assertFalse(result["ok"])
        self.assertFalse(result.get("unknown", False))
        self.assertEqual(mt5.sent, 0)
        self.assertEqual(mt5.positions, [])

    def test_demo_smoke_order_preserves_correlation_marker_on_open_and_close(self):
        mt5 = FakeMT5()
        mt5.positions = []
        correlation_id = "0123456789abcdef0123456789abcdef"
        result = MT5Gateway(mt5).place_demo_smoke_order("ENVIAR TESTE DEMO", correlation_id)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["correlation_id"], correlation_id)
        self.assertEqual(len(mt5.requests), 2)
        self.assertTrue(all("SC0123456789" in request["comment"] for request in mt5.requests))
        self.assertEqual(mt5.positions, [])

    def test_demo_smoke_order_send_exception_is_unknown_and_never_retried(self):
        mt5 = FakeMT5()
        mt5.positions = []

        def ambiguous_send(_request):
            mt5.sent += 1
            mt5.positions.append(SimpleNamespace(ticket=99, symbol="EURUSD#", type=0, volume=0.01,
                                                  price_open=1.1, price_current=1.1, sl=0, tp=0,
                                                  profit=0, time=1, magic=209221001,
                                                  comment="SL1 demo test"))
            raise TimeoutError("simulated response loss after acceptance")

        mt5.order_send = ambiguous_send
        result = MT5Gateway(mt5).place_demo_smoke_order("ENVIAR TESTE DEMO")
        self.assertFalse(result["ok"])
        self.assertTrue(result["unknown"])
        self.assertTrue(result["position_may_remain"])
        self.assertTrue(result["no_retry"])
        self.assertEqual(mt5.sent, 1)
        self.assertEqual(len(mt5.positions), 1)

    def test_demo_smoke_order_accepted_without_identified_position_stays_unknown(self):
        mt5 = FakeMT5()
        mt5.positions = []

        def accepted_but_not_reconciled(request):
            mt5.sent += 1
            return SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, order=99, deal=100)

        mt5.order_send = accepted_but_not_reconciled
        result = MT5Gateway(mt5).place_demo_smoke_order("ENVIAR TESTE DEMO")
        self.assertFalse(result["ok"])
        self.assertTrue(result["unknown"])
        self.assertTrue(result["position_may_remain"])
        self.assertEqual(mt5.sent, 1)

    def test_demo_smoke_order_partial_close_reports_remaining_exposure_without_retry(self):
        mt5 = FakeMT5()
        mt5.positions = []
        original_send = mt5.order_send

        def partial_close(request):
            if request.get("position") == 99:
                mt5.sent += 1
                return SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE_PARTIAL, order=22, deal=23)
            return original_send(request)

        mt5.order_send = partial_close
        result = MT5Gateway(mt5).place_demo_smoke_order("ENVIAR TESTE DEMO")
        self.assertFalse(result["ok"])
        self.assertTrue(result["close"]["partial"])
        self.assertTrue(result["position_remains"])
        self.assertTrue(result["no_retry"])
        self.assertEqual(mt5.sent, 2)
        self.assertEqual([position.ticket for position in mt5.positions], [99])

    def test_engine_strategy_order_requires_arm_demo_and_empty_account(self):
        mt5 = FakeMT5()
        gateway = MT5Gateway(mt5)
        blocked = gateway.send_demo_strategy_order("EURUSD#", "BUY", 0.01, 1.08, 1.09, 3)
        self.assertFalse(blocked["ok"])
        self.assertEqual(mt5.sent, 0)

    def test_strategy_order_requires_the_approved_account_identity(self):
        mt5 = FakeMT5()
        mt5.positions = []
        gateway = MT5Gateway(mt5)
        self.assertTrue(gateway.arm_order_engine("strategy", "DEMO", "42@Demo"))
        result = gateway.send_demo_strategy_order("EURUSD#", "BUY", 0.01, 1.08, 1.09, 3,
                                                  expected_account_fingerprint="99@OtherDemo")
        self.assertTrue(result["blocked"])
        self.assertEqual(mt5.sent, 0)

    def test_account_switch_during_preflight_blocks_before_order_send(self):
        mt5 = FakeMT5()
        mt5.positions = []
        mt5.test_symbol = SimpleNamespace(name="EURUSD#", trade_mode=4, order_mode=127,
                                          volume_min=0.01, volume_max=100, filling_mode=2,
                                          digits=5, trade_exemode=2)
        mt5.symbol_info = lambda _symbol: mt5.test_symbol
        mt5.symbol_info_tick = lambda _symbol: SimpleNamespace(ask=1.082, bid=1.081)
        mt5.order_check_hook = lambda: setattr(mt5, "account_login", 43)
        gateway = MT5Gateway(mt5)
        self.assertTrue(gateway.arm_order_engine("strategy", "DEMO", "42@Demo"))
        result = gateway.send_demo_strategy_order("EURUSD#", "BUY", 0.01, 1.08, 1.09, 3,
                                                  expected_account_fingerprint="42@Demo")
        self.assertTrue(result["blocked"])
        self.assertEqual(mt5.sent, 0)

    def test_concurrent_strategy_entries_can_submit_only_one_position(self):
        mt5 = FakeMT5()
        mt5.positions = []
        mt5.test_symbol = SimpleNamespace(name="EURUSD#", trade_mode=4, order_mode=127,
                                          volume_min=0.01, volume_max=100, filling_mode=2,
                                          digits=5, trade_exemode=2)
        mt5.symbol_info = lambda _symbol: mt5.test_symbol
        mt5.symbol_info_tick = lambda _symbol: SimpleNamespace(ask=1.082, bid=1.081)
        mt5.order_check = lambda _request: (time.sleep(0.05) or SimpleNamespace(retcode=0))
        gateway = MT5Gateway(mt5)
        self.assertTrue(gateway.arm_order_engine("strategy", "DEMO", "42@Demo"))
        start = threading.Barrier(3)

        def send():
            start.wait()
            return gateway.send_demo_strategy_order("EURUSD#", "BUY", 0.01, 1.08, 1.09, 3,
                                                    expected_account_fingerprint="42@Demo")

        threads = [threading.Thread(target=lambda: results.append(send())) for _ in range(2)]
        results = []
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(mt5.sent, 1)
        self.assertEqual(sum(bool(result.get("ok")) for result in results), 1)

    def test_mt5_connection_is_initialized_once_and_shutdown_cleanly(self):
        mt5 = FakeMT5()
        gateway = MT5Gateway(mt5)
        self.assertTrue(gateway.state()["connected"])
        self.assertTrue(gateway.state()["connected"])
        self.assertEqual(mt5.initialize_count, 1)
        gateway.shutdown()
        self.assertFalse(gateway._initialized)

    def test_failed_connection_attempt_is_throttled(self):
        mt5 = FakeMT5()
        mt5.initialize = lambda **_kwargs: (setattr(mt5, "initialize_count", mt5.initialize_count + 1) or False)
        mt5.last_error = lambda: (1, "not connected")
        gateway = MT5Gateway(mt5)
        self.assertFalse(gateway.state()["connected"])
        self.assertFalse(gateway.state()["connected"])
        self.assertEqual(mt5.initialize_count, 1)


if __name__ == "__main__":
    unittest.main()
