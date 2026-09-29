"""Authorized integration check; requires explicit flag for one DEMO round trip."""
import sys,json,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import MetaTrader5 as mt5
from scalperlab.web import create_app
from scalperlab.mt5_gateway import MT5Gateway

def main():
    evidence=[]
    output=Path(__file__).resolve().parents[1]/'backups'/'qa-clock-recovery.json'
    def record(name,value):
        evidence.append({'case':name,'result':value})
        output.write_text(json.dumps(evidence,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    assert mt5.initialize()
    gateway=MT5Gateway(mt5)
    app=create_app(mt5=gateway)
    client=app.test_client(); headers={'X-ScalperLab-Token':app.config['APP_TOKEN']}
    port=app.extensions['scalper_mt5']; ticket=None
    try:
        state=port.state(); assert state['account']['mode']=='DEMO'
        assert not mt5.positions_get() and not mt5.orders_get()
        record('bridge',state['clock_bridge']); assert state['clock_bridge']['ok']
        clock=client.post('/api/system/clock/synchronize',headers=headers,json={})
        record('clock',{'status':clock.status_code,'body':clock.json})
        tick=port.current_tick('EURUSD#'); assert tick['ok'],tick
        stop=round(tick['ask']-.001,5)
        preview=client.post('/api/settings/risk/preview',headers=headers,json={
            'engine':'analyst','symbol':'EURUSD#','side':'BUY','stop':stop})
        record('preview',{'status':preview.status_code,'body':preview.json})
        for symbol,tf in [('EURUSD#','M15'),('BTCUSD#','M5')]:
            # Functional test assumptions, not validated broker cost estimates.
            replay=client.post('/api/analyst/replay',headers=headers,json={
                'symbol':symbol,'timeframe':tf,'bars':1200,'costs_confirmed':True,
                'slippage_points':2,'commission_per_lot_round_turn':7,
                'swap_long_per_lot_per_utc_rollover':-10,'swap_short_per_lot_per_utc_rollover':-10})
            record('replay_'+symbol,{'status':replay.status_code,'body':replay.json,
                                    'costs_are_functional_test_assumptions':True})
        offline=client.post('/api/analyst/replay-saved',headers=headers,json={})
        record('offline',{'status':offline.status_code,'body':offline.json})
        if '--send-demo' in sys.argv:
            assert clock.status_code==200 and clock.json['mt5_status']=='verified', 'UTC not verified'
            account=port.state()['account']; assert account['mode']=='DEMO'
            fingerprint=f"{account['login']}@{account['server']}"
            policy=app.extensions['scalper_risk_settings'].profile('analyst')
            assert policy['max_volume']>=.02
            assert port.arm_order_engine('analyst','DEMO',fingerprint)
            tick=port.current_tick('EURUSD#');assert tick['ok']
            stop=round(tick['ask']-.001,5);target=round(tick['ask']+.002,5)
            result=port.send_demo_analyst_order('EURUSD#','BUY',.02,stop,target,
                expected_account_fingerprint=fingerprint,risk_cash=5,
                risk_policy=policy,min_reward_risk=1.5)
            record('order_002',result); ticket=result.get('ticket')
            assert result.get('ok') and result.get('reconciled'),result
            positions=mt5.positions_get(ticket=ticket)
            record('server_position',[p._asdict() for p in positions or []])
            assert positions and positions[0].sl>0 and positions[0].tp>0 and positions[0].volume==.02
    except Exception:
        record('failure',traceback.format_exc())
    finally:
        if ticket:
            armed=port.arm_demo('ATIVAR SOMENTE DEMO');record('close_arm',armed)
            if armed.get('ok'):record('close',port.close_demo_position(ticket,'FECHAR POSIÇÃO DEMO'))
        port.disarm_order_engine('analyst')
        record('positions_after',[p._asdict() for p in mt5.positions_get() or []])
        record('orders_after',[p._asdict() for p in mt5.orders_get() or []])
        mt5.shutdown()

if __name__=='__main__':main()
