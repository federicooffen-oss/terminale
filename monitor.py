"""Monitoraggio dei portafogli modello Binario F.
Ogni giorno scarica i prezzi, ricalcola il VaR (parametrico, 99%, 5 anni, annualizzato con radice di 256)
e controlla la deriva dei pesi rispetto all'ultimo ribilanciamento. Scrive consulenza/monitor.json
e, se compare un nuovo avviso, monitor/avvisi.md (da cui il workflow apre una segnalazione GitHub: arriva per email)."""
import json,os,sys,re,datetime as dt
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__));ROOT=os.path.dirname(BASE)
Z=2.326;GG=256
BAND_MAX=[5.8,11.6,23.3,46.5];BANDS=['Basso','Medio-basso','Medio-alto','Alto']
TS_Y0=3.0;TS_SY=1.0          # come nell'app: rendimento ipotizzato 3%, volatilità annua del rendimento 1 punto
BONDS={}                      # isin -> {nome,tipo,tasso,scadenza,vol (% annua), scaduto}
GRP={}                        # isin -> gruppo dell'ETF (E azionario, B obbligazionario, M monetario, G oro, H high yield)
def durata_mod(t,oggi=None):
    oggi=oggi or dt.date.today();T=(dt.date.fromisoformat(t['scadenza'])-oggi).days/365.25
    if T<=0:return 0.0
    y=TS_Y0/100
    if t.get('tipo')=='CCT':return min(T,.25)
    if t.get('tipo') in('BOT','CTZ') or t.get('tasso')==0:return T/(1+y)
    c=(TS_Y0 if t.get('tasso') is None else t['tasso'])/100;n=max(1,int(np.ceil(T*2-1e-9)));pv=pt=0.0
    for i in range(n):
        tt=T-i*.5
        if tt<=0:continue
        d=(c/2+(1 if i==0 else 0))/(1+y/2)**(2*tt);pv+=d;pt+=tt*d
    return pt/pv/(1+y/2)
def gruppo(nome):
    t=nome.lower()
    if re.search(r'gold|physical|silver|commodit|bitcoin|crypto|\boro\b',t):return 'G'
    if re.search(r'overnight|\bcash\b|money market|ultrashort|t-bill|estr|rate swap|liquidity',t):return 'M'
    if re.search(r'high yield|\bhy\b',t):return 'H'
    if re.search(r'bond|govt|government|treasury|gilt|aggregate|corporate|inflation|credit|ibonds|btp|oat|bund|floating|obblig',t):return 'B'
    return 'E'
def rho_titolo(g):  # correlazione ipotizzata tra un titolo di Stato e uno strumento di gruppo g (come nell'app)
    return {'B':.8,'H':.45,'M':.05,'G':.2,'E':.1}.get(g,.1)
def var_annuo(w,rets):
    """VaR annuo (%) di un portafoglio con pesi w (dict isin->frazione): ETF da covarianza campionaria (media zero);
    titoli di Stato da duration (vol. = duration x 1 punto) con correlazioni ipotizzate. Giorni = radice di 256."""
    ec=[c for c in w if c in rets.columns];bc=[c for c in w if c in BONDS]
    cols=ec+bc;x=np.array([w[c] for c in cols]);x=x/x.sum()
    sub=rets[ec].dropna() if ec else None            # finestra comune: solo i giorni in cui esistono tutti gli strumenti
    if sub is not None and len(sub)<250:sub=rets[ec]
    n=len(cols);cov=np.zeros((n,n))
    if ec:cov[:len(ec),:len(ec)]=sub.cov().values
    sd_b=[BONDS[c]['vol']/100/np.sqrt(GG) for c in bc]
    for a,ca in enumerate(bc):
        i=len(ec)+a
        for b,cb in enumerate(bc):
            cov[i,len(ec)+b]=sd_b[a]*sd_b[b]*(1 if a==b else .8)
        for j,ce in enumerate(ec):
            sdj=float(np.sqrt(max(cov[j,j],0)));cov[i,j]=cov[j,i]=sd_b[a]*sdj*rho_titolo(GRP.get(ce,'E'))
    sd=float(np.sqrt(max(x@cov@x,0.0)))
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
        oggi_=dt.date.today()
        for c in p['pesi']:
            b=BONDS.get(c)
            if not b:continue
            gg=(dt.date.fromisoformat(b['scadenza'])-oggi_).days
            if gg<=0:
                stato='allarme';msgs.append(f"Il titolo {b['nome']} ({c}) è scaduto il {b['scadenza']}: il capitale ({p['pesi'][c]}% del portafoglio) è rientrato e va reinvestito.")
            elif gg<=30:
                if stato=='ok':stato='preavviso'
                msgs.append(f"Il titolo {b['nome']} ({c}) scade tra {gg} giorni ({b['scadenza']}): prepara il reinvestimento del {p['pesi'][c]}%.")
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

def backtest(cfg,prices,anni=5):
    """Storico retrospettivo dei portafogli modello (pesi attuali, ribilanciamento periodico, al lordo dei costi di consulenza).
    Dove manca lo storico di uno strumento uso un sostituto simile: per un ETF recente la media degli ETF dello stesso gruppo
    (azionario, obbligazionario, monetario, oro) con dati in quel giorno; per BTP/BOT/titoli di Stato gli ETF obbligazionari/monetari
    a minor volatilita' (breve scadenza). E' un'approssimazione, non un risultato reale."""
    import numpy as np
    p=prices.ffill();r=p.pct_change(fill_method=None)
    r=r.where(r.abs()<0.15)      # scarta variazioni giornaliere assurde (errori nei dati): il giorno viene riempito col sostituto
    fine=r.index[-1];inizio=fine-pd.DateOffset(years=anni);r=r[r.index>inizio]
    g=lambda c:GRP.get(c,'E')
    # proxy per gruppo (media giornaliera degli strumenti del gruppo con dati)
    prox={k:r[[c for c in r.columns if g(c)==k]].median(axis=1,skipna=True) for k in 'EBMGH' if any(g(c)==k for c in r.columns)}
    # proxy titoli di Stato: i 3 strumenti B/M meno volatili con storico lungo
    cand=[c for c in r.columns if g(c) in 'BM' and r[c].count()>=0.8*len(r)]
    cand=sorted(cand,key=lambda c:r[c].std())[:3]
    stato=r[cand].median(axis=1,skipna=True) if cand else prox.get('M',prox.get('B'))
    out={}
    for k,pf in cfg['portafogli'].items():
        tot=sum(pf['pesi'].values())/100
        cols={};reale=0.0
        for c,x in pf['pesi'].items():
            w=x/100
            if c in r.columns and r[c].count()>=0.2*len(r):
                s_=r[c].copy();gap=s_.isna()
                s_[gap]=(prox.get(g(c)) if prox.get(g(c)) is not None else stato)[gap]
                cols[c]=(s_,w);reale+=w*(1-gap.mean())
            else:
                cols[c]=(stato if stato is not None else prox.get('B'),w)
        ret=sum((s_.fillna(0)*w) for s_,w in cols.values())/tot
        ok=sum((s_.notna()*w) for s_,w in cols.values())/tot
        ret=ret[ok>=0.95].dropna()
        if len(ret)<120:continue
        nav=(1+ret).cumprod()*100
        anni_eff=(nav.index[-1]-nav.index[0]).days/365.25
        cagr=(nav.iloc[-1]/100)**(1/anni_eff)-1 if anni_eff>0 else 0
        mdd=float((nav/nav.cummax()-1).min())
        vol=float(ret.std()*np.sqrt(252))
        m=nav.resample('ME').last().dropna()
        m12=m.pct_change(12).dropna()
        out[k]={'nome':pf['nome'],'dal':str(nav.index[0].date()),'al':str(nav.index[-1].date()),'anni':round(anni_eff,2),
                'cagr':round(float(cagr),4),'mdd':round(mdd,4),'vol':round(vol,4),'peggior_12m':round(float(m12.min()),4) if len(m12) else None,
                'copertura':round(float(reale/tot),3),
                'serie':[[str(d.date()),round(float(v),2)] for d,v in m.items()]}
    return out

def main():
    cfg=json.load(open(os.path.join(BASE,'modelli.json')))
    out_path=os.path.join(BASE,'monitor.json')
    prev=json.load(open(out_path)).get('portafogli',{}) if os.path.exists(out_path) else {}
    BONDS.clear()
    for i,t in (cfg.get('titoli') or {}).items():
        d=durata_mod(t);BONDS[i]={'nome':t.get('nome',i),'tipo':t.get('tipo'),'tasso':t.get('tasso'),'scadenza':t['scadenza'],'vol':max(.1,d*TS_SY),'duration':round(d,2)}
    isins_pf=sorted({c for p in cfg['portafogli'].values() for c in p['pesi'] if c not in BONDS})
    cat_p=os.path.join(BASE,'catalogo_isin.json')
    seed=json.load(open(cat_p)) if os.path.exists(cat_p) else []
    nomi=dict(cfg.get('nomi',{}));nomi.update({x['isin']:x['nome'] for x in seed if x['isin'] not in nomi})
    GRP.update({i:gruppo(n) for i,n in nomi.items()})
    tutti=isins_pf+[x['isin'] for x in seed if x['isin'] not in isins_pf]
    tick,nomi_y=risolvi(tutti,nomi,os.path.join(BASE,'isin_cache.json'))
    try:
        for i_,t_ in json.load(open(os.path.join(BASE,'ticker_manuali.json'))).items():
            if i_ in nomi:nomi_y[i_]=nomi[i_]      # per i ticker forzati a mano vale il nome mio, non quello di Yahoo
    except Exception:pass
    prices=scarica(tick)
    ok=[i for i in tutti if i in prices.columns and prices[i].dropna().shape[0]>=60]   # ETF recenti: li tengo, 'n' dice quanti giorni di storico ci sono
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
    try:
        sp_=os.path.join(BASE,'storico_portafogli.json');gia=os.path.exists(sp_) and json.load(open(sp_)).get('metodo')=='sostituti-v2'
        if os.environ.get('STORICO') not in ('1','true') and gia:raise RuntimeError('storico già presente: ricalcolo solo su richiesta')
        bt=backtest(cfg,prices)
        json.dump({'aggiornato':adesso,'metodo':'sostituti-v2','nota':'Storico retrospettivo (backtest) con i pesi attuali dei portafogli, al lordo dei costi di consulenza. Non è un risultato realmente ottenuto da clienti. I rendimenti passati non sono indicativi di quelli futuri.','portafogli':bt},open(os.path.join(BASE,'storico_portafogli.json'),'w'),ensure_ascii=False,separators=(',',':'))
        print('storico portafogli:',len(bt))
    except Exception as e:
        import traceback;traceback.print_exc();print('storico non calcolato:',e)
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
