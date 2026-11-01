"""Censimento titoli di Stato italiani (BTP, BOT, CCT, CTZ) da Borsa Italiana (MOT, prezzi differiti).
Scrive titoli.json: ISIN, nome, tipo, prezzo, cedola, scadenza. Toglie da solo i titoli scaduti."""
import re,json,os,sys,time,datetime as dt,urllib.request
from html.parser import HTMLParser
BASE=os.path.dirname(os.path.abspath(__file__))
TIPI={'btp':'BTP','bot':'BOT','cct':'CCT','ctz':'CTZ'}
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
def get(url):
    r=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Language':'it-IT,it;q=0.9'})
    return urllib.request.urlopen(r,timeout=30).read().decode('utf-8','replace')
class T(HTMLParser):
    def __init__(s):super().__init__();s.rows=[];s.r=None;s.c=None;s.hdr=[]
    def handle_starttag(s,t,a):
        if t=='tr':s.r=[]
        elif t in('td','th') and s.r is not None:s.c=''
    def handle_endtag(s,t):
        if t in('td','th') and s.r is not None and s.c is not None:s.r.append(' '.join(s.c.split()));s.c=None
        elif t=='tr' and s.r is not None:
            if s.r:s.rows.append(s.r)
            s.r=None
    def handle_data(s,d):
        if s.c is not None:s.c+=d
def num(x):
    m=re.search(r'-?\d[\d.]*,?\d*',x or '');
    if not m:return None
    try:return float(m.group(0).replace('.','').replace(',','.'))
    except ValueError:return None
def pagina(tipo,n):
    h=get(f'https://www.borsaitaliana.it/borsa/obbligazioni/mot/{tipo}/lista.html?&page={n}')
    p=T();p.feed(h);out=[]
    for r in p.rows:
        txt=' '.join(r)
        m=re.search(r'\b(IT\d{10})\b',txt)
        d=re.findall(r'\b(\d{2})/(\d{2})/(\d{4})\b',txt)
        if not m or not d:continue
        dd=d[-1];scad=f'{dd[2]}-{dd[1]}-{dd[0]}'
        # colonne attese: Isin | Descrizione | Ultimo | Cedola | Scadenza (le celle ISIN possono contenere testo ripetuto)
        celle=[c for c in r if c]
        try:i=[k for k,c in enumerate(celle) if re.search(r'\d{2}/\d{2}/\d{4}',c)][-1]
        except IndexError:continue
        nome=next((c for c in celle if c!=m.group(1) and re.search(r'[A-Za-z]{3}',c) and not c.startswith(m.group(1)) and 'Aggiungi' not in c),'')
        out.append({'isin':m.group(1),'nome':nome,'prezzo':num(celle[i-2]) if i>=2 else None,'cedola':num(celle[i-1]) if i>=1 else None,'scadenza':scad})
    return out
def main():
    oggi=dt.date.today();tutti={};log=[]
    for tipo,etich in TIPI.items():
        n=1;visti=0
        while n<60:
            try:righe=pagina(tipo,n)
            except Exception as e:log.append(f'{tipo} pag {n}: {e}');break
            nuovi=[x for x in righe if x['isin'] not in tutti]
            if not righe or not nuovi:break
            for x in nuovi:x['tipo']=etich;tutti[x['isin']]=x
            visti+=len(nuovi);n+=1;time.sleep(0.5)
        log.append(f'{etich}: {visti} titoli in {n-1} pagine')
    vivi=[x for x in tutti.values() if dt.date.fromisoformat(x['scadenza'])>oggi and x['prezzo']]
    scaduti=[x['isin'] for x in tutti.values() if dt.date.fromisoformat(x['scadenza'])<=oggi]
    vivi.sort(key=lambda x:x['scadenza'])
    prev=os.path.join(BASE,'titoli.json')
    if not vivi and os.path.exists(prev):print('Nessun titolo letto: tengo il file precedente');print('\n'.join(log));return 0
    json.dump({'aggiornato':dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'),'fonte':'Borsa Italiana MOT (prezzi differiti)','titoli':vivi,'scaduti_rimossi':scaduti},open(prev,'w'),ensure_ascii=False,separators=(',',':'))
    print('\n'.join(log));print('titoli attivi:',len(vivi),'scaduti rimossi:',len(scaduti));return 0
if __name__=='__main__':sys.exit(main())
