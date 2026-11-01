"""Monitoraggio dei portafogli modello Binario F.
Ogni giorno scarica i prezzi, ricalcola il VaR (parametrico, 99%, 5 anni, annualizzato con radice di 256)
e controlla la deriva dei pesi rispetto all'ultimo ribilanciamento. Scrive consulenza/monitor.json
e, se compare un nuovo avviso, monitor/avvisi.md (da cui il workflow apre una segnalazione GitHub: arriva per email)."""
import json,os,sys,re,datetime as dt
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__));ROOT=os.path.dirname(BASE)
Z=2.326;GG=256
BAND_MAX=[5.8,11.6,23.3,46.5];BANDS=['Basso','Medio-basso','Medio-alto','Alto']
def var_annuo(w,rets):
    """VaR annuo (%) di un portafoglio con pesi w (dict isin->frazione) sui rendimenti giornalieri, covarianza campionaria, media zero."""
    cols=[c for c in w if c in rets.columns];x=np.array([w[c] for c in cols]);x=x/x.sum()
    sub=rets[cols].dropna()                      # finestra comune: solo i giorni in cui esistono tutti gli strumenti
    if len(sub)<250:sub=rets[cols]               # storico troppo corto: uso le coppie disponibili
    cov=sub.cov().values;sd=float(np.sqrt(max(x@cov@x,0.0)))
    return Z*sd*np.sqrt(GG)*100
def band_of(v):return next((i for i,m in enumerate(BAND_MAX) if v<=m),3)
def deriva(w,prices,date0):
    """Pesi attuali se il cliente ha ribilanciato in date0 e non ha più toccato nulla."""
    p=prices.loc[prices.index>=pd.Timestamp(date0)]
    if len(p)<2:return dict(w)
    rel=p.iloc[-1]/p.iloc[0];v={c:w[c]*float(rel.get(c,1.0)) for c in w};t=sum(v.values())
    return {c:v[c]/t for c in v}
def valuta(cfg,prices,prev=None):
    rets=prices.pct_change().dropna(how='all').tail(5*GG);res={};avvisi=[]
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
STOP={'acc','dist','ucits','etf','etc','1c','1d','2c','2d','4c','4d','dr','c','d','the','di','ex'}
ACC={'acc','1c','2c','4c','c'};DIST={'dist','1d','2d','4d','d'}
def _tok(t):return {w for w in re.findall(r'[a-z0-9]+',t.lower()) if w not in STOP and len(w)>1}
def _classe(t):
    w=set(re.findall(r'[a-z0-9]+',t.lower()));return 'a' if w&ACC else 'd' if w&DIST else None
def _cerca(isin,nome,yf):
    """Cerca per nome (Yahoo per ISIN trova una sola borsa). Sceglie Milano, poi Xetra, con nome coerente."""
    ok=_tok(nome);ca=_classe(nome)
    pulito=re.sub(r'\([^)]*\)','',nome);pulito=' '.join(w for w in pulito.split() if w.lower() not in STOP)
    for qs in (pulito,' '.join(pulito.split()[:4])):
        q=yf.Search(qs,max_results=20).quotes
        def nm(x):return x.get('longname') or x.get('shortname') or ''
        c=[x for x in q if x.get('symbol','').split('.')[-1] in ('MI','DE') and ok and len(ok&_tok(nm(x)))/len(ok)>=0.8
           and not (ca and _classe(nm(x)) and _classe(nm(x))!=ca)]
        c.sort(key=lambda x:(len(_tok(nm(x))-ok),x['symbol'].endswith('.DE')))
        for x in c:
            if _eur(x['symbol'],yf):return x['symbol'],x.get('longname')
        if c:return c[0]['symbol'],c[0].get('longname')
    return None,None
def risolvi(isins,nomi,cache_path,minuti=40):
    """ISIN -> ticker Milano/Xetra. Salva man mano; ricomincia da dove era arrivato (cache)."""
    import yfinance as yf,time
    cache=json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    if cache.get('_v')!=6:cache={'_v':6,'_nomi':cache.get('_nomi',{}),'_falliti':{},**{k:v for k,v in cache.items() if not k.startswith('_') and v}}
    man_p=os.path.join(BASE,'ticker_manuali.json')
    man=json.load(open(man_p)) if os.path.exists(man_p) else {}
    oggi=dt.date.today();t0=time.time();nuovi=0
    for i in isins:
        if i in man:cache[i]=man[i];continue
        if cache.get(i):continue
        f=cache['_falliti'].get(i)
        if f and (oggi-dt.date.fromisoformat(f)).days<14:continue
        if time.time()-t0>minuti*60:print('tempo finito: si riprende al prossimo avvio');break
        try:
            nome=nomi.get(i,i)
            try:
                q0=yf.Search(i,max_results=3).quotes
                if q0 and q0[0].get('longname'):nome=q0[0]['longname']
            except Exception:pass
            t,ln=_cerca(i,nome,yf);time.sleep(0.2)
            if t:cache[i]=t;cache['_nomi'][i]=ln or nome;cache['_falliti'].pop(i,None)
            else:cache['_falliti'][i]=oggi.isoformat();print('NESSUN TICKER MI/DE per',i,nome)
        except Exception as e:print('ISIN non risolto',i,e);cache['_falliti'][i]=oggi.isoformat()
        nuovi+=1
        if nuovi%25==0:json.dump(cache,open(cache_path,'w'),indent=1)
    json.dump(cache,open(cache_path,'w'),indent=1)
    return {i:cache[i] for i in isins if cache.get(i)},cache.get('_nomi',{})
def scarica(tick):
    import yfinance as yf
    tk=sorted(set(tick.values()));parts=[]
    for k in range(0,len(tk),60):
        d=yf.download(tk[k:k+60],period='6y',auto_adjust=True,progress=False,threads=True)['Close']
        if isinstance(d,pd.Series):d=d.to_frame(tk[k])
        parts.append(d)
    df=pd.concat(parts,axis=1)
    inv={};[inv.setdefault(t,[]).append(i) for i,t in tick.items()]
    out={}
    for t,isl in inv.items():
        if t in df.columns:
            for i in isl:out[i]=df[t]
    return pd.DataFrame(out).dropna(how='all').ffill()
def main():
    cfg=json.load(open(os.path.join(BASE,'modelli.json')))
    out_path=os.path.join(BASE,'monitor.json')
    prev=json.load(open(out_path)).get('portafogli',{}) if os.path.exists(out_path) else {}
    isins_pf=sorted({c for p in cfg['portafogli'].values() for c in p['pesi']})
    cat_p=os.path.join(BASE,'catalogo_isin.json')
    seed=json.load(open(cat_p)) if os.path.exists(cat_p) else []
    nomi=dict(cfg.get('nomi',{}));nomi.update({x['isin']:x['nome'] for x in seed if x['isin'] not in nomi})
    tutti=isins_pf+[x['isin'] for x in seed if x['isin'] not in isins_pf]
    tick,nomi_y=risolvi(tutti,nomi,os.path.join(BASE,'isin_cache.json'))
    prices=scarica(tick)
    ok=[i for i in tutti if i in prices.columns and prices[i].dropna().shape[0]>=250]
    # stesso codice di borsa per più ISIN (classi diverse dello stesso ETF o abbinamento sbagliato): tengo il primo, segnalo gli altri
    visto={};ambigui=[]
    for i in list(ok):
        t=tick[i]
        if t in visto:ambigui.append({'isin':i,'uguale_a':visto[t],'ticker':t});ok.remove(i)
        else:visto[t]=i
    mancanti=[i for i in isins_pf if i not in ok]
    res,avvisi=valuta(cfg,prices,prev)
    rets=prices.pct_change().dropna(how='all').tail(5*GG)
    ultimo=lambda c:round(float(prices[c].dropna().iloc[-1]),4)
    cols=[c for c in isins_pf if c in ok]
    mercato={'isin':cols,'sd':[round(float(rets[c].std()),6) for c in cols],'prezzi':[ultimo(c) for c in cols],'corr':[[round(float(x),3) for x in r] for r in rets[cols].corr(min_periods=120).fillna(0).values],'giorni':int(len(rets)),'storico':[int(rets[c].count()) for c in cols]}
    # controllo di coerenza: obbligazionari "normali" con volatilità quasi nulla = probabile ETF sbagliato (es. 0-6 mesi)
    anomalie=[]
    for c in ok:
        vol=float(rets[c].std())*16*100 if c in rets.columns else None;n=nomi.get(c,'')
        if vol is not None and re.search(r'bond|govt|government',n,re.I) and not re.search(r'0-6|0-1|overnight|ultrashort|cash|floating|rolling|target|ibonds',n,re.I) and vol<1.0:
            anomalie.append({'isin':c,'nome':n,'ticker':tick[c],'volatilita_annua':round(vol,2),'messaggio':'Volatilità quasi nulla per un obbligazionario: probabile ETF diverso da quello atteso. Verifica il codice di borsa.'})
    adesso=dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    out={'aggiornato':adesso,'ultimo_prezzo':str(prices.index[-1].date()),'strumenti_senza_dati':mancanti,'anomalie':[a for a in anomalie if a['isin'] in isins_pf],'mercato':mercato,'portafogli':res}
    json.dump(out,open(out_path,'w'),ensure_ascii=False,indent=1)
    print('OK',out['ultimo_prezzo'],'portafogli senza dati:',mancanti)
    # catalogo completo (per la ricerca nell'app): prezzo, volatilità e correlazioni reali di ogni strumento
    ca=[c for c in tutti if c in ok]
    rc=rets[ca]
    cat={'aggiornato':adesso,'strumenti':[{'isin':c,'nome':nomi_y.get(c) or nomi.get(c,c),'ticker':tick[c],'prezzo':ultimo(c),'sd':round(float(rc[c].std()),6),'n':int(rc[c].count())} for c in ca],
         'senza_prezzo':[{'isin':c,'nome':nomi.get(c,c)} for c in tutti if c not in ok and c not in [a['isin'] for a in ambigui]],'ambigui':ambigui,'anomalie':anomalie,
         'corr':[[int(round(float(x)*100)) for x in r] for r in rc.corr(min_periods=120).fillna(0).values],'giorni':int(len(rc))}
    json.dump(cat,open(os.path.join(BASE,'catalogo.json'),'w'),ensure_ascii=False,separators=(',',':'))
    print('catalogo:',len(ca),'con prezzo,',len(tutti)-len(ca),'senza')
    ap=os.path.join(BASE,'avvisi.md')
    if os.path.exists(ap):os.remove(ap)
    if avvisi:
        L=['# Avvisi sui portafogli modello','']
        for k,n,sx,m in avvisi:L+= [f"## {k} · {n} — {sx.upper()}"]+[f"- {x}" for x in m]+['']
        L.append('Decisione e ribilanciamento restano al consulente. Dettagli nell\'app, scheda Monitoraggio.')
        open(ap,'w').write('\n'.join(L))
if __name__=='__main__':main()
