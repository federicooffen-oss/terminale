#!/usr/bin/env python3
"""Scarica lo storico dei prezzi (gratis, senza chiavi) e scrive data.json.
Fonte principale: Yahoo Finance (endpoint pubblico chart). Riserva: Stooq.
Se uno strumento non si scarica, resta l'ultimo dato valido."""
import json, sys, time, datetime as dt, csv, io, os
import requests

DAYS = 400
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36'}
HERE = os.path.dirname(os.path.abspath(__file__))

def yahoo(sym):
    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}',
                     params={'range': '2y', 'interval': '1d'}, headers=UA, timeout=25)
    r.raise_for_status()
    res = r.json()['chart']['result'][0]
    ts = res['timestamp']; cl = res['indicators']['quote'][0]['close']
    return {dt.datetime.utcfromtimestamp(t).strftime('%Y-%m-%d'): c for t, c in zip(ts, cl) if c is not None}

def stooq(sym):
    s = sym.lower()
    s = s + '.us' if '.' not in s and '-' not in s else s.replace('-usd', '.v')
    r = requests.get('https://stooq.com/q/d/l/', params={'s': s, 'i': 'd'}, headers=UA, timeout=25)
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
    series, fail = {}, []
    for u in uni:
        d = None
        for fn in (yahoo, stooq):
            try:
                d = fn(u['y'])
                if len(d) > 30: break
            except Exception as e:
                d = None
            time.sleep(0.4)
        if not d or len(d) <= 30:
            if u['t'] in old: d = old[u['t']]
            else: fail.append(u['t']); continue
        series[u['t']] = d
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
