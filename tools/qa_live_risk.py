"""Explicitly authorized DEMO validation. Never starts an autonomous engine."""
import json,re,urllib.request,urllib.error,datetime,pathlib,sys
BASE=sys.argv[1]
ROOT=pathlib.Path(__file__).resolve().parents[1]
html=urllib.request.urlopen(BASE).read().decode()
TOKEN=re.search(r'name="app-token" content="([^"]+)',html)[1]
results=[]
def call(path,data=None,auth=True):
    headers={'Origin':BASE,'Content-Type':'application/json'}
    if auth: headers['X-ScalperLab-Token']=TOKEN
    req=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=120) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.load(e)
def record(name,response):
    results.append({'case':name,'status':response[0],'result':response[1]})
    print(name,response[0],json.dumps(response[1],ensure_ascii=True)[:650],flush=True)
state=call('/api/state')[1]
assert state['mt5']['account']['mode']=='DEMO'
assert not any(state[k]['state']['running'] for k in ('engine','analyst'))
settings=state['risk_settings']
backup=ROOT/'backups'/'risk-before-live-qa.json'
backup.write_text(json.dumps(settings,indent=2),encoding='utf-8')
try:
    record('unauthenticated_write',call('/api/settings/risk',{},auth=False))
    for engine in ('analyst','strategy'):
        for mode in ('risk_pct','risk_cash','fixed_lot'):
            profile={**settings['profiles'][engine],'sizing_mode':mode,'fixed_volume':.02,'max_volume':.02}
            record(engine+'_'+mode,call('/api/settings/risk',{'engine':engine,'profile':profile,'daily_loss_limit_pct':settings['daily_loss_limit_pct']}))
    profile={**settings['profiles']['analyst'],'margin_reserve_pct':99.99}
    record('margin_reserve_save',call('/api/settings/risk',{'engine':'analyst','profile':profile,'daily_loss_limit_pct':settings['daily_loss_limit_pct']}))
    for value in (-1,100,'NaN'):
        record('invalid_margin_'+str(value),call('/api/settings/risk',{'engine':'analyst','profile':{**profile,'margin_reserve_pct':value},'daily_loss_limit_pct':2}))
    record('preview_live',call('/api/settings/risk/preview',{'engine':'analyst','symbol':'EURUSD#','side':'BUY','stop':1.136}))
    record('replay_without_cost_confirmation',call('/api/analyst/replay',{'symbol':'EURUSD#','timeframe':'M15','bars':1200}))
finally:
    for engine,profile in settings['profiles'].items():
        record('restore_'+engine,call('/api/settings/risk',{'engine':engine,'profile':profile,'daily_loss_limit_pct':settings['daily_loss_limit_pct']}))
    (ROOT/'backups'/'qa-live-risk-results.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
