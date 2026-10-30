#!/usr/bin/env python3
"""Scarica lo storico dei prezzi (gratis, senza chiavi) e scrive data.json.
Fonte principale: Yahoo Finance (endpoint pubblico chart). Riserva: Stooq.
Se uno strumento non si scarica, resta l'ultimo dato valido."""
import json, sys, time, datetime as dt, csv, io, os
T0 = time.time(); BUDGET = 420   # secondi massimi totali
import requests
try:
    import yfinance as yf
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'yfinance'])
    import yfinance as yf

DAYS = 400
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36'}
HERE = os.path.dirname(os.path.abspath(__file__))

def yahoo(sym):
    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}',
                     params={'range': '2y', 'interval': '1d'}, headers=UA, timeout=8)
    r.raise_for_status()
    res = r.json()['chart']['result'][0]
    ts = res['timestamp']; cl = res['indicators']['quote'][0]['close']
    return {dt.datetime.utcfromtimestamp(t).strftime('%Y-%m-%d'): c for t, c in zip(ts, cl) if c is not None}

def yfin(sym):
    last = None
    for k in range(3):
        try:
            h = yf.Ticker(sym).history(period='2y', interval='1d', auto_adjust=False)
            if len(h) > 30:
                return {i.strftime('%Y-%m-%d'): float(c) for i, c in zip(h.index, h['Close']) if c == c}
        except Exception as e:
            last = e
        time.sleep(2 + 3 * k)
    raise last or ValueError('yfinance vuoto')

def stooq(sym):
    s = sym.lower()
    s = s + '.us' if '.' not in s and '-' not in s else s.replace('-usd', '.v')
    r = requests.get('https://stooq.com/q/d/l/', params={'s': s, 'i': 'd'}, headers=UA, timeout=8)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if not rows or 'Close' not in rows[0]: raise ValueError('stooq vuoto')
    return {x['Date']: float(x['Close']) for x in rows if x['Close']}

def main():
    uni = json.load(open(f'{HERE}/universe.json'))
    old = {}
    try:
        o = json.load(open(f'{HERE}/data.json'))
        old = {i['t']: dict(zip(o['dates'], i['c'])) for i in o['inst']}
    except Exception: pass
    series, fail, tried_ok = {}, [], 0
    for n, u in enumerate(uni, 1):
        if time.time() - T0 > BUDGET:
            print('Tempo massimo raggiunto, mi fermo qui'); fail += [x['t'] for x in uni[n-1:]]; break
        d, why = None, ''
        for fn in (yfin, yahoo):
            try:
                d = fn(u['y'])
                if len(d) > 30: why = fn.__name__; break
            except Exception as e:
                d = None; why += f'{fn.__name__}: {type(e).__name__} {str(e)[:90]} | '
        if d and len(d) > 30:
            tried_ok += 1; print(f"[{n}/{len(uni)}] {u['t']} ok ({why})", flush=True)
        else:
            print(f"[{n}/{len(uni)}] {u['t']} ERRORE {why}", flush=True)
            if u['t'] in old: d = old[u['t']]
            else: fail.append(u['t']); d = None
            if n >= 6 and tried_ok == 0:
                print('I primi 6 strumenti non si scaricano: rete o fonte bloccata. Mi fermo.'); sys.exit(1)
        if d: series[u['t']] = d
        time.sleep(0.3)
    if len(series) < len(uni) * 0.5:
        print('Troppi errori:', fail); sys.exit(1)
    last = max(max(s) for s in series.values())
    first = (dt.date.fromisoformat(last) - dt.timedelta(days=DAYS)).isoformat()
    dates = sorted({d for s in series.values() for d in s if first <= d <= last})
    inst = []
    for u in uni:
        s = series.get(u['t'])
        if not s: continue
        c, prev = [], None
        for d in dates:
            prev = s.get(d, prev)          # riporta l'ultimo prezzo nei giorni di chiusura
            c.append(None if prev is None else round(prev, 4))
        inst.append({'t': u['t'], 'n': u['n'], 'g': u['g'], 'w': u['w'], 'c': c})
    out = {'updated': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'source': 'Yahoo Finance / Stooq', 'dates': dates, 'inst': inst}
    json.dump(out, open(f'{HERE}/data.json', 'w'), separators=(',', ':'))
    print('ok', len(inst), 'strumenti; non scaricati:', fail)

if __name__ == '__main__': main()
