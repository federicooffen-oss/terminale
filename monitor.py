"""Monitoraggio dei portafogli modello Binario F.
Ogni giorno scarica i prezzi, ricalcola il VaR (parametrico, 99%, 5 anni, annualizzato con radice di 256)
e controlla la deriva dei pesi rispetto all'ultimo ribilanciamento. Scrive consulenza/monitor.json
e, se compare un nuovo avviso, monitor/avvisi.md (da cui il workflow apre una segnalazione GitHub: arriva per email)."""
import json,os,sys,datetime as dt
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__));ROOT=os.path.dirname(BASE)
Z=2.326;GG=256
BAND_MAX=[5.8,11.6,23.3,46.5];BANDS=['Basso','Medio-basso','Medio-alto','Alto']
def var_annuo(w,rets):
    """VaR annuo (%) di un portafoglio con pesi w (dict isin->frazione) sui rendimenti giornalieri, covarianza campionaria, media zero."""
    cols=[c for c in w if c in rets.columns];x=np.array([w[c] for c in cols]);x=x/x.sum()
    cov=rets[cols].cov().values;sd=float(np.sqrt(x@cov@x))
    return Z*sd*np.sqrt(GG)*100
def band_of(v):return next((i for i,m in enumerate(BAND_MAX) if v<=m),3)
def deriva(w,prices,date0):
    """Pesi attuali se il cliente ha ribilanciato in date0 e non ha più toccato nulla."""
    p=prices.loc[prices.index>=pd.Timestamp(date0)]
    if len(p)<2:return dict(w)
    rel=p.iloc[-1]/p.iloc[0];v={c:w[c]*float(rel.get(c,1.0)) for c in w};t=sum(v.values())
    return {c:v[c]/t for c in v}
def valuta(cfg,prices,prev=None):
    rets=prices.pct_change().dropna(how='all').tail(5*GG).fillna(0.0);res={};avvisi=[]
    th=cfg['soglie'];prev=prev or {}
    for k,p in cfg['portafogli'].items():
        w={c:x/100 for c,x in p['pesi'].items()}
        v0=var_annuo(w,rets);wd=deriva(w,prices,p['ultimo_ribilanciamento']);vd=var_annuo(wd,rets)
        dm=max(abs(wd[c]-w[c]) for c in w)*100
        lim=BAND_MAX[p['fascia']];msgs=[];stato='ok'
        if v0>lim or vd>lim:
            stato='allarme';msgs.append(f"Il VaR annuo ({max(v0,vd):.1f}%) supera il limite della fascia {BANDS[p['fascia']]} ({lim}%).")
        elif max(v0,vd)>=lim*th['preavviso_var']:
            stato='preavviso';msgs.append(f"Il VaR annuo ({max(v0,vd):.1f}%) ha raggiunto il {th['preavviso_var']*100:.0f}% del limite della fascia {BANDS[p['fascia']]} ({lim}%).")
        if dm>=th['deriva_punti']:
            if stato=='ok':stato='preavviso'
            msgs.append(f"Un peso si è spostato di {dm:.1f} punti dal modello dall'ultimo ribilanciamento ({p['ultimo_ribilanciamento']}): valuta un ribilanciamento.")
        res[k]={'nome':p['nome'],'fascia':p['fascia'],'limite':lim,'var_modello':round(v0,2),'var_attuale':round(vd,2),'deriva_max':round(dm,2),'stato':stato,'messaggi':msgs,
                'pesi_attuali':{c:round(wd[c]*100,2) for c in wd}}
        if stato!='ok' and prev.get(k,{}).get('stato')!=stato:avvisi.append((k,p['nome'],stato,msgs))
    return res,avvisi
def _eur(sym,yf):
    try:return yf.Ticker(sym).fast_info.get('currency')=='EUR'
    except Exception:return False
def scarica(isins,cache_path):
    import yfinance as yf
    cache=json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    if cache.get('_v')!=3:cache={'_v':3}   # rifà la ricerca: preferisce quotazioni in euro
    man_p=os.path.join(BASE,'ticker_manuali.json')
    man=json.load(open(man_p)) if os.path.exists(man_p) else {}
    for i in isins:
        if i in man:cache[i]=man[i];continue
        if cache.get(i):continue
        try:
            q=[x for x in yf.Search(i,max_results=10).quotes if x.get('symbol') and not x['symbol'].startswith(i[:6])]
            for suf in ('MI','DE'):   # priorità: Borsa Italiana, poi Xetra
                pref=[x['symbol'] for x in q if x['symbol'].endswith('.'+suf)]
                pick=next((t for t in pref if _eur(t,yf)),None) or (pref[0] if pref else None)
                if pick:break
            if not pick:print('NESSUN TICKER MI/DE per',i,[x.get('symbol') for x in q])
            cache[i]=pick
        except Exception as e:print('ISIN non risolto',i,e);cache[i]=None
    json.dump(cache,open(cache_path,'w'),indent=1)
    tick={i:t for i,t in cache.items() if i!='_v' and t and i in isins}
    df=yf.download(list(tick.values()),period='6y',auto_adjust=True,progress=False)['Close']
    if isinstance(df,pd.Series):df=df.to_frame(list(tick.values())[0])
    inv={t:i for i,t in tick.items()};df=df.rename(columns=inv).dropna(how='all').ffill()
    return df
def main():
    cfg=json.load(open(os.path.join(BASE,'modelli.json')))
    out_path=os.path.join(BASE,'monitor.json')
    prev=json.load(open(out_path)).get('portafogli',{}) if os.path.exists(out_path) else {}
    isins=sorted({c for p in cfg['portafogli'].values() for c in p['pesi']})
    prices=scarica(isins,os.path.join(BASE,'isin_cache.json'))
    mancanti=[i for i in isins if i not in prices.columns or prices[i].dropna().shape[0]<250]
    res,avvisi=valuta(cfg,prices,prev)
    out={'aggiornato':dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),'ultimo_prezzo':str(prices.index[-1].date()),'strumenti_senza_dati':mancanti,'portafogli':res}
    json.dump(out,open(out_path,'w'),ensure_ascii=False,indent=1)
    print('OK',out['ultimo_prezzo'],'senza dati:',mancanti)
    ap=os.path.join(BASE,'avvisi.md')
    if os.path.exists(ap):os.remove(ap)
    if avvisi:
        L=['# Avvisi sui portafogli modello','']
        for k,n,s,m in avvisi:L+= [f"## {k} · {n} — {s.upper()}"]+[f"- {x}" for x in m]+['']
        L.append('Decisione e ribilanciamento restano al consulente. Dettagli nell\'app, scheda Monitoraggio.')
        open(ap,'w').write('\n'.join(L))
if __name__=='__main__':main()
