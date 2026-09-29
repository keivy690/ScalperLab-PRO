import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import time

from scalperlab.db import Database
from scalperlab.risk_settings import RiskSettings, validate_policy
from scalperlab.position_sizing import size_order
from scalperlab.web import create_app
from scalperlab.mt5_gateway import MT5Gateway
from test_mt5_gateway import FakeMT5


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'risk.sqlite3')
        self.risk = RiskSettings(self.db)
        self.account = dict(login=1, server='broker', mode='DEMO', equity=1000)
        self.deals = []
        self.gateway = SimpleNamespace(history_deals=lambda *a: {'available': True, 'items': self.deals})

    def tearDown(self):
        self.temp.cleanup()

    def test_limit_survives_restart_profile_change_and_recovery(self):
        self.assertTrue(self.risk.daily_check(self.gateway, self.account)['ok'])
        self.account['equity'] = 989
        self.assertFalse(self.risk.daily_check(self.gateway, self.account)['ok'])
        other = RiskSettings(self.db)
        other.save('strategy', validate_policy({}), 5)
        self.account['equity'] = 1010
        self.assertFalse(other.daily_check(self.gateway, self.account)['ok'])
        self.account['login'] = 2
        self.assertTrue(other.daily_check(self.gateway, self.account)['ok'])

    def test_deposit_and_withdrawal_are_not_profit_or_loss(self):
        self.risk.daily_check(self.gateway, self.account)
        self.deals.append({'ticket': 1, 'type': 2, 'profit': 100})
        self.account['equity'] = 1095
        self.risk.daily_check(self.gateway, self.account)
        self.assertEqual(self.risk.daily_snapshot(self.account)['loss_cash'], 5)
        self.deals.append({'ticket': 2, 'type': 2, 'profit': -200})
        self.account['equity'] = 895
        self.assertTrue(self.risk.daily_check(self.gateway, self.account)['ok'])
        self.assertEqual(self.risk.daily_snapshot(self.account)['loss_cash'], 5)

    def test_history_unavailable_does_not_reset_reference(self):
        self.risk.daily_check(self.gateway, self.account)
        baseline = self.risk.daily_snapshot(self.account)['reference_at']
        self.gateway.history_deals = lambda *a: {'available': False}
        self.assertFalse(self.risk.daily_check(self.gateway, self.account)['ok'])
        self.assertEqual(baseline, self.risk.daily_snapshot(self.account)['reference_at'])

    def test_revised_or_missing_balance_history_blocks_without_reset(self):
        self.deals.append({'ticket': 10, 'type': 2, 'profit': 100})
        self.assertTrue(self.risk.daily_check(self.gateway, self.account)['ok'])
        baseline = self.risk.daily_snapshot(self.account)['reference_at']
        self.deals[0]['profit'] = 200
        self.assertFalse(self.risk.daily_check(self.gateway, self.account)['ok'])
        self.deals.clear()
        self.assertFalse(self.risk.daily_check(self.gateway, self.account)['ok'])
        self.assertEqual(baseline, self.risk.daily_snapshot(self.account)['reference_at'])

    def test_audited_port_blocks_stale_policy_and_shared_daily_limit(self):
        from scalperlab.connectors.audit import AuditedTradingPort
        from unittest.mock import Mock
        send = Mock()
        connector = SimpleNamespace(terminal_id='test', state=lambda: {'account':self.account},
                                    history_deals=self.gateway.history_deals,
                                    send_demo_analyst_order=send, send_demo_strategy_order=send)
        port = AuditedTradingPort(connector, self.db)
        port.risk_settings = self.risk
        stale = self.risk.profile('analyst')
        self.risk.save('analyst', {'max_volume':.02}, 1)
        result = port.send_demo_analyst_order('EURUSD#','BUY',.01,1.,1.2,
                                            risk_cash=1,risk_policy=stale)
        self.assertFalse(result['ok'])
        self.assertIn('Perfil de risco mudou',result['detail'])
        self.account['equity'] = 989
        for method,extra,engine in [(port.send_demo_analyst_order,(), 'analyst'),
                                  (port.send_demo_strategy_order,(1,), 'strategy')]:
            result=method('EURUSD#','BUY',.01,1.,1.2,*extra,
                          risk_cash=1,risk_policy=self.risk.profile(engine))
            self.assertFalse(result['ok'])
            self.assertIn('Limite diário',result['detail'])
        send.assert_not_called()

    def test_unavailable_profit_or_margin_never_produces_volume(self):
        symbol=SimpleNamespace(name='EURUSD#',volume_min=.01,volume_step=.01,volume_max=100,volume_limit=0)
        broker=SimpleNamespace(ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,
                               account_info=lambda:SimpleNamespace(margin_free=1000),
                               order_calc_profit=lambda *a:None,
                               order_calc_margin=lambda *a:10)
        self.assertFalse(size_order(broker,symbol,'BUY',1.1,1,10,{})['ok'])
        broker.order_calc_profit=lambda *a:-1
        for margin in (None,float('nan'),float('inf')):
            broker.order_calc_margin=lambda *a:margin
            self.assertFalse(size_order(broker,symbol,'BUY',1.1,1,10,{})['ok'])

    def test_invalid_numeric_values_are_rejected(self):
        for value in ['nan', 'inf', -1, True]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.risk.save('analyst', {'max_volume': value}, 1)
        with self.assertRaises(ValueError):
            self.risk.save('analyst', {'sizing_mode': 'fixed_lot', 'fixed_volume': 2, 'max_volume': 1}, 1)

    def test_size_uses_broker_step_and_never_increases_to_minimum(self):
        symbol = SimpleNamespace(name='INDEX', volume_min=.1, volume_step=.1, volume_max=100, volume_limit=0)
        mt5 = SimpleNamespace(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
                              account_info=lambda: SimpleNamespace(margin_free=1000),
                              order_calc_profit=lambda t,s,v,e,sl: -v * 100,
                              order_calc_margin=lambda t,s,v,e: v*100)
        self.assertFalse(size_order(mt5,symbol,'BUY',100,99,5,{'max_volume':1})['ok'])
        result = size_order(mt5,symbol,'BUY',100,99,39,{'max_volume':1})
        self.assertEqual(result['volume'], .3)
        self.assertEqual(result['estimated_loss'], 30)
        self.assertEqual(result['margin_required'], 30)
        self.assertFalse(size_order(mt5,symbol,'BUY',100,99,39,
                                   {'sizing_mode':'fixed_lot','fixed_volume':.35,'max_volume':1})['ok'])
        self.assertFalse(size_order(mt5,symbol,'BUY',100,99,39,
                                   {'sizing_mode':'fixed_lot','fixed_volume':.4,'max_volume':1})['ok'])
        self.assertFalse(size_order(mt5,symbol,'BUY',100,99,39,
                                   {'max_volume':1, 'margin_reserve_pct':99})['ok'])

    def test_api_saves_profiles_and_refuses_changes_while_running(self):
        app = create_app(database=self.db, mt5=MT5Gateway(FakeMT5()), token='test')
        client = app.test_client()
        headers = {'X-ScalperLab-Token':'test'}
        data = {'engine':'analyst','profile':{'sizing_mode':'risk_cash','risk_cash':25,'max_volume':.1},'daily_loss_limit_pct':2}
        self.assertEqual(client.post('/api/settings/risk',json=data).status_code,403)
        response = client.post('/api/settings/risk',json=data,headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(RiskSettings(self.db).budget('analyst',self.account),25)
        with patch.object(app.extensions['scalper_analyst'], 'snapshot', return_value={'state':{'running':True}}):
            self.assertEqual(client.post('/api/settings/risk',json=data,headers=headers).status_code,409)

    def test_preflight_accepts_configured_volume_above_old_cap(self):
        mt5 = FakeMT5()
        mt5.positions = []
        mt5.symbol_info = lambda _: SimpleNamespace(name='EURUSD#',volume_min=.01,volume_max=100,
            volume_step=.01,trade_mode=4,volume_limit=0,digits=5,filling_mode=2,trade_exemode=2)
        gateway = MT5Gateway(mt5)
        gateway.arm_order_engine('strategy','DEMO','42@Demo')
        gateway.send_demo_strategy_order('EURUSD#','BUY',.02,1.08,1.09,3,
            expected_account_fingerprint='42@Demo',risk_cash=10,risk_policy=validate_policy({'max_volume':.02}))
        self.assertEqual(mt5.sent,1)
        self.assertEqual(mt5.requests[0]['volume'],.02)

    def test_preflight_rejects_wrong_step_and_margin_reserve(self):
        mt5 = FakeMT5(); mt5.positions = []
        mt5.symbol_info = lambda _: SimpleNamespace(name='EURUSD#',volume_min=.01,volume_max=100,
            volume_step=.01,trade_mode=4,volume_limit=0,digits=5,filling_mode=2,trade_exemode=2)
        gateway = MT5Gateway(mt5); gateway.arm_order_engine('strategy','DEMO','42@Demo')
        for volume, policy in [(.015, {'max_volume':1}),(.02,{'max_volume':1,'margin_reserve_pct':99.9})]:
            r=gateway.send_demo_strategy_order('EURUSD#','BUY',volume,1.08,1.09,3,
                expected_account_fingerprint='42@Demo',risk_cash=10,risk_policy=validate_policy(policy))
            self.assertFalse(r['ok'])
        self.assertEqual(mt5.sent,0)

    def test_analyst_passes_saved_budget_and_policy_to_order_path(self):
        from scalperlab.market_analyst import MarketAnalystEngine
        from unittest.mock import Mock
        self.risk.save('analyst', {'risk_per_trade_pct':1, 'max_volume':.2}, 5)
        account = {**self.account, 'trade_allowed':True, 'trade_expert':True}
        gateway = SimpleNamespace(
            state=lambda: {'connected':True,'account':account,'terminal':{'trade_allowed':True}},
            history_deals=self.gateway.history_deals,
            risk_volume=Mock(return_value={'ok':True,'volume':.02,'estimated_loss':8}),
            send_demo_analyst_order=Mock(return_value={'ok':True,'reconciled':True,'ticket':1,'detail':'confirmed'}))
        engine = MarketAnalystEngine(self.db,gateway,risk_settings=self.risk)
        engine.state.update(running=True,mode='demo',account_fingerprint='1@broker',day_start_equity=1000)
        analysis={'timeframe':'M5','last_closed_bar_at':'now','technical':{'atr14':.1},
                  'decision':{'order_eligible':True,'side':'BUY','stop':1.,'target':1.3,'reasons':[]}}
        with patch.object(engine,'_clock_failure',return_value=None):
            engine._maybe_execute('EURUSD#',analysis,{}, {'ok':True,'time':time.time(),'ask':1.1,'bid':1.099})
        self.assertEqual(gateway.risk_volume.call_args.args[4],10)
        self.assertEqual(gateway.risk_volume.call_args.kwargs['policy']['max_volume'],.2)
        self.assertEqual(gateway.send_demo_analyst_order.call_args.kwargs['risk_policy']['risk_per_trade_pct'],1)

    def test_preview_api_uses_saved_settings_and_does_not_send(self):
        app=create_app(database=self.db,mt5=MT5Gateway(FakeMT5()),token='test')
        risk=app.extensions['scalper_risk_settings']
        risk.save('strategy',{'risk_per_trade_pct':.5,'max_volume':2},1)
        from unittest.mock import Mock
        sizing=Mock(return_value={'ok':True,'volume':.05})
        app.extensions['scalper_mt5']=SimpleNamespace(
            validate_market_symbols=lambda symbols:{'available':True,'valid':True},
            current_tick=lambda symbol:{'ok':True,'ask':1.1,'bid':1.099,'time':time.time()},
            state=lambda:{'account':self.account},risk_volume=sizing)
        result=app.test_client().post('/api/settings/risk/preview',headers={'X-ScalperLab-Token':'test'},
                                      json={'engine':'strategy','symbol':'EURUSD#','side':'BUY','stop':1})
        self.assertEqual(result.status_code,200)
        self.assertEqual(sizing.call_args.args[4],5)
        self.assertEqual(sizing.call_args.kwargs['policy']['max_volume'],2)
