"""Variazione giornaliera degli strumenti dei clienti.
Legge i prezzi di chiusura/ultimo prezzo da Yahoo (ticker Milano/Xetra già censiti) e scrive variazioni.csv:
isin,ticker,prezzo×10000,chiusura_precedente×10000,variazione_in_punti_base,data_ultima_seduta,aggiornamento
(solo numeri interi: così il foglio Google li legge uguali in qualsiasi impostazione di lingua)."""
import json,os,re,sys,datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
def jl(nome,default):
    p=os.path.join(BASE,nome)
    try:return json.load(open(p))
    except Exception:return default
def universo():
    nomi={};ordine=[]
    for x in jl('isin_clienti.json',[]):nomi[x['isin']]=x.get('nome','');ordine.append(x['isin'])
    cfg=jl('modelli.json',{})
    bonds=set((cfg.get('titoli') or {}).keys())
    for p in (cfg.get('portafogli') or {}).values():
        for i in p.get('pesi',{}):
            if i not in bonds and i not in nomi:nomi[i]=(cfg.get('nomi') or {}).get(i,i);ordine.append(i)
    return nomi,ordine
def trova_ticker(nomi,ordine,yf):
    import monitor as M
    cache=jl('isin_cache.json',{});man=jl('ticker_manuali.json',{});extra=jl('ticker_clienti.json',{})
    tick={};nuovi=False
    for i in ordine:
        t=man.get(i) or extra.get(i) or cache.get(i)
        if not t:
            try:
                t,_=M._cerca(i,nomi.get(i) or i,yf)
                if not t:
                    q=yf.Search(i,max_results=5).quotes
                    t=next((x['symbol'] for x in q if x.get('symbol')),None)
            except Exception as e:print('ticker non trovato per',i,e);t=None
            if t:extra[i]=t;nuovi=True
        if t:tick[i]=t
    json.dump(extra,open(os.path.join(BASE,'ticker_clienti.json'),'w'),indent=1)
    return tick
def serie(df,t):
    try:
        s=df[t]['Close'] if isinstance(df.columns,pd.MultiIndex) else df['Close']
        return s.dropna()
    except Exception:return None
def main():
    import yfinance as yf
    nomi,ordine=universo();tick=trova_ticker(nomi,ordine,yf)
    if not tick:print('nessun ticker');return 1
    ts=sorted(set(tick.values()))
    df=yf.download(ts,period='10d',interval='1d',auto_adjust=False,progress=False,group_by='ticker',threads=True)
    righe=[]
    for i in ordine:
        t=tick.get(i)
        if not t:continue
        s=serie(df,t)
        if s is None or len(s)<2:continue
        last,prev=float(s.iloc[-1]),float(s.iloc[-2])
        if prev<=0:continue
        righe.append({'isin':i,'ticker':t,'p':last,'pp':prev,'bp':int(round((last/prev-1)*1e4)),'d':int(s.index[-1].strftime('%Y%m%d'))})
    if not righe:print('nessun prezzo letto: tengo il file precedente');return 1
    dmax=max(r['d'] for r in righe)
    ora=int(dt.datetime.now(ZoneInfo('Europe/Rome')).strftime('%Y%m%d%H%M'))
    out=['isin,ticker,prezzo,prec,var_bp,data,ora']
    for r in righe:
        bp='' if r['d']<dmax else str(r['bp'])           # strumento non quotato oggi (dato vecchio): n.d.
        out.append('%s,%s,%d,%d,%s,%d,%d'%(r['isin'],r['ticker'],round(r['p']*1e4),round(r['pp']*1e4),bp,r['d'],ora))
    open(os.path.join(BASE,'variazioni.csv'),'w').write('\n'.join(out)+'\n')
    print('variazioni.csv:',len(righe),'strumenti su',len(ordine),'· seduta',dmax)
    return 0
if __name__=='__main__':sys.exit(main())
