"""Storico lungo (fino a 15 anni) dei portafogli modello.
Ogni ETF del portafoglio e' ricondotto a una 'famiglia' (azionario mondo, minima volatilita', quality, small cap, dividendi, emergenti,
oro, obbligazionari breve/lungo/inflazione/aggregate/high yield, monetario) con un ETF di riferimento a storia lunga.
Dove la famiglia e' piu' recente di 15 anni, i giorni mancanti sono riempiti con la famiglia piu' vicina (es. quality -> azionario mondo).
Pesi attuali dei portafogli, ribilanciamento mensile, al lordo della commissione di consulenza. E' un'approssimazione.
Scrive storico_lungo.json."""
import json,os,datetime as dt
import numpy as np,pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
ANNI=15
# famiglia -> candidati (ordine di preferenza) e famiglia di ripiego per i giorni senza dati
FAM={
 'WORLD':(['EUNL.DE','IWDA.AS','SWDA.MI','URTH','VT'],None),
 'ALLW':(['VWRL.AS','VWCE.DE','VT','EUNL.DE'],'WORLD'),
 'MINVOL':(['ACWV','USMV','MVOL.L'],'WORLD'),
 'QUAL':(['QUAL','IWFQ.L','IWQU.L'],'WORLD'),
 'MOM':(['MTUM','IWFM.L'],'WORLD'),
 'SMALL':(['IUSN.DE','WSML.L','IWM','VB'],'WORLD'),
 'HDY':(['VYM','VYMI','FDIV.L'],'WORLD'),
 'EM':(['EEM','IEMG','EUNM.DE'],'WORLD'),
 'IT':(['XLK','VGT','IUIT.L'],'WORLD'),
 'DJ':(['DIA','EXI2.DE'],'WORLD'),
 'GOLD':(['4GLD.DE','SGLD.MI','EGLN.L','GLD'],None),
 'MONEY':(['XEON.DE','XEON.MI','CSH2.MI','SHV'],None),
 'SHORT':(['IBGS.L','IBGS.AS','SE13.MI','SHY'],'MONEY'),
 'LONG':(['IEGA.AS','IEGA.MI','IBGM.AS','IEF'],'SHORT'),
 'IL':(['IBCI.DE','IBCI.AS','TIP'],'LONG'),
 'AGG':(['IEAG.L','EUNA.DE','AGGH.MI','AGG'],'LONG'),
 'HY':(['HYG','JNK'],'LONG')}
# pesi % per famiglia (dai pesi degli ETF dei portafogli modello)
PF={
 'P1':('Liquidità Plus',{'MONEY':90,'SHORT':10}),
 'P2':('Prudente Anti-inflazione',{'ALLW':7,'LONG':20,'MONEY':25,'SHORT':40,'IL':8}),
 'P3':('Rendita Prudente',{'DJ':10,'HDY':10,'LONG':50,'SHORT':10,'MONEY':20}),
 'P4':('Bilanciato Prudente',{'MINVOL':10,'WORLD':5,'QUAL':15,'LONG':10,'MONEY':15,'SHORT':35,'IL':10}),
 'P5':('ESG Prudente',{'WORLD':23,'EM':7,'LONG':15,'MONEY':15,'SHORT':25,'AGG':15}),
 'P6':('Bilanciato Crescita',{'ALLW':30,'HDY':10,'MINVOL':10,'MOM':5,'MONEY':10,'SHORT':25,'IL':10}),
 'P7':('Rendita Dinamica',{'WORLD':25,'HDY':30,'LONG':10,'HY':5,'SHORT':20,'MONEY':10}),
 'P8':('ESG Crescita',{'WORLD':58,'EM':7,'LONG':10,'MONEY':5,'SHORT':10,'AGG':10}),
 'P9':('Crescita Globale',{'GOLD':5,'MINVOL':10,'SMALL':8,'HDY':15,'QUAL':40,'MOM':7,'MONEY':5,'SHORT':10}),
 'P10':('Crescita Dinamica',{'SMALL':8,'HDY':12,'QUAL':40,'MINVOL':15,'IT':3,'MOM':7,'MONEY':5,'SHORT':10})}
def scegli(dl):
    sc={};info={}
    for f,(lst,_) in FAM.items():
        best=None
        for t in lst:
            try:s=dl(t)
            except Exception as e:print('errore',t,e);continue
            if s is None:continue
            s=s.dropna()
            if len(s)<500:print('troppo corto/assente',t);continue
            anni=(s.index[-1]-s.index[0]).days/365.25;print(f,t,round(anni,1),'anni')
            if anni>=ANNI+0.2:best=(t,s,anni);break
            if best is None or anni>best[2]:best=(t,s,anni)
        if best:sc[f]=best[1];info[f]=best[0]
    return sc,info
def calcola(sc):
    r=pd.DataFrame({f:s.pct_change() for f,s in sc.items()})
    r=r.where(r.abs()<0.15)
    # riempimento con la famiglia di ripiego
    tent=0
    for _ in range(4):
        for f,(l,fb) in FAM.items():
            if f in r.columns and fb and fb in r.columns:r[f]=r[f].fillna(r[fb])
    fine=r.index[-1];inizio=fine-pd.DateOffset(years=ANNI)
    out={}
    for k,(nome,pesi) in PF.items():
        w={f:x/100 for f,x in pesi.items()}
        if any(f not in r.columns for f in w):print('manca famiglia per',k,[f for f in w if f not in r.columns]);continue
        R=r[list(w)];R=R[R.index>inizio].dropna()
        if len(R)<500:continue
        wv=pd.Series(w);cur=wv*100.0;vals=[];mese=None
        for d,row in R.iterrows():
            if mese is not None and d.month!=mese:cur=wv*cur.sum()
            mese=d.month;cur=cur*(1+row);vals.append(float(cur.sum()))
        nv=pd.Series(vals,index=R.index);anni=(nv.index[-1]-nv.index[0]).days/365.25
        cagr=(nv.iloc[-1]/100)**(1/anni)-1;mdd=float((nv/nv.cummax()-1).min());vol=float(nv.pct_change().std()*np.sqrt(252))
        m=nv.resample('ME').last().dropna()
        out[k]={'nome':nome,'dal':str(nv.index[0].date()),'al':str(nv.index[-1].date()),'anni':round(anni,2),'cagr':round(float(cagr),4),'mdd':round(mdd,4),'vol':round(vol,4),'copertura':1.0,
                'serie':[[str(d.date()),round(float(v),2)] for d,v in m.items()]}
    return out
def main():
    import yfinance as yf
    def dl(t):
        d=yf.download(t,period='max',auto_adjust=True,progress=False)['Close']
        return d.iloc[:,0] if hasattr(d,'columns') else d
    sc,info=scegli(dl);print('scelti:',info)
    out=calcola(sc)
    res={'aggiornato':dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),'metodo':'famiglie-v2','fonti':info,
         'nota':"Storico retrospettivo (backtest) con i pesi attuali del portafoglio, usando per ogni tipo di ETF un indice/ETF di riferimento a storia lunga e ribilanciamento mensile, al lordo della commissione di consulenza. Dove il riferimento ha storia più breve si usa l'azionario mondo o l'obbligazionario più simile. Non è un risultato realmente ottenuto da clienti. I rendimenti passati non sono indicativi di quelli futuri.",
         'portafogli':out}
    json.dump(res,open(os.path.join(BASE,'storico_lungo.json'),'w'),ensure_ascii=False,separators=(',',':'))
    print('portafogli:',len(out),{k:(v['anni'],v['cagr'],v['mdd']) for k,v in out.items()})
if __name__=='__main__':main()
