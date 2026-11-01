"""Anagrafica dei titoli di Stato italiani dal file ufficiale del Tesoro (MEF, 'Titoli di Stato in circolazione').
Legge l'ultimo file Titoli_di_Stato_in_circolazione*.xls caricato nel repository e scrive titoli_stato.json.
Niente prezzi: solo ISIN, tipo, cedola, scadenza. I titoli scaduti non vengono scritti."""
import glob,json,os,re,sys,datetime as dt
import pandas as pd
BASE=os.path.dirname(os.path.abspath(__file__))
def tipo_serie(t):
    t=str(t).upper().strip()
    if t.startswith('BOT'):return 'BOT','BOT'
    if t.startswith('CCT'):return 'CCT','CCT-EU'
    base={'BTPI':'BTP€i (indicizzato inflazione)','BTPITALIA':'BTP Italia','BTPVALORE':'BTP Valore','BTPVALORE INSIEME':'BTP Valore Insieme','BTPFUTURA':'BTP Futura','BTPGREEN':'BTP Green','BTP':'BTP'}
    return 'BTP',base.get(t,t.title())
def main():
    fs=sorted(glob.glob(os.path.join(BASE,'Titoli_di_Stato_in_circolazione*.xls*')),key=os.path.getmtime)
    if not fs:print('Nessun file del Tesoro nel repository: titoli_stato.json non aggiornato');return 0
    f=fs[-1];raw=pd.read_excel(f,header=None)
    agg=None
    for v in raw.iloc[0].tolist():
        try:agg=pd.Timestamp(v).strftime('%Y-%m-%d')
        except Exception:pass
    d=raw.iloc[4:,:8].copy();d.columns=['isin','desc','tipo','emis','scad','fv','importo','ced']
    d=d[d['isin'].astype(str).str.match(r'^IT\d{10}$')];oggi=dt.date.today();out=[]
    for _,r in d.iterrows():
        sc=pd.to_datetime(r['scad'],dayfirst=True,errors='coerce')
        if pd.isna(sc) or sc.date()<=oggi:continue
        tipo,serie=tipo_serie(r['tipo']);ced=r['ced']
        if str(ced).lower().startswith('zero') or tipo=='BOT':tasso=0.0
        elif str(r['fv']).upper()=='V':tasso=None
        else:
            try:tasso=round(float(ced)*2,4)
            except Exception:tasso=None
        if tasso is not None and tasso>15:tasso=None      # strutture particolari (es. BTP Valore Insieme): cedola non annua
        em=pd.to_datetime(r['emis'],errors='coerce')
        out.append({'isin':r['isin'],'tipo':tipo,'serie':serie,'nome':' '.join(str(r['desc']).split()),'tasso':tasso,'variabile':str(r['fv']).upper()=='V',
                    'emissione':None if pd.isna(em) else em.strftime('%Y-%m-%d'),'scadenza':sc.strftime('%Y-%m-%d'),'importo_mln':None if pd.isna(r['importo']) else float(r['importo'])})
    out.sort(key=lambda x:x['scadenza'])
    json.dump({'aggiornato':agg or '','fonte':'Ministero dell\'Economia e delle Finanze - Dipartimento del Tesoro, Titoli di Stato in circolazione','file':os.path.basename(f),'titoli':out},
              open(os.path.join(BASE,'titoli_stato.json'),'w'),ensure_ascii=False,separators=(',',':'))
    print('titoli_stato.json:',len(out),'titoli in circolazione al',agg)
    return 0
if __name__=='__main__':sys.exit(main())
