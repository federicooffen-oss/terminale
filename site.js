/* Binario F · sito pubblico: dati, costi, grafici, simulatore */
const BF={
  APP:'consulenza.html',
  DATI:'storico_portafogli.json',
  /* ipotesi di rendimento lordo annuo per classe (non sono previsioni): modificabili qui */
  ASS:{Azionario:6.0,Obbligazionario:3.0,Monetario:2.0,Oro:3.0},
  /* costi medi dei fondi comuni: ESMA, Costs and Performance of EU Retail Investment Products 2025 (dati 2024). Fondi misti non ETF. */
  FUND:{corr:1.44,tot:2.0},
  COL:{Azionario:'#2D4A3A',Obbligazionario:'#6C8EAD',Monetario:'#B8B07A',Oro:'#D18A1C'},
  BANDS:['Basso','Medio-basso','Medio-alto','Alto']
};
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const eur=(n,d=0)=>n.toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d})+' €';
const pc=(n,d=1)=>(n*100).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d})+'%';
const pcs=(n,d=1)=>(n>0?'+':n<0?'−':'')+Math.abs(n*100).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d})+'%';
/* commissioni (proposta: da confermare) */
const FEE_SC=[[50000,.005],[150000,.0035],[500000,.0025],[Infinity,.0015]],FEE_MIN=100;
function feeCont(c){let f=0,p=0;for(const [m,r] of FEE_SC){if(c>p)f+=(Math.min(c,m)-p)*r;p=m}return Math.max(FEE_MIN,Math.round(f))}
const UNA_SC=[[10000,60],[25000,90],[50000,140],[100000,200],[250000,300],[Infinity,400]];
const feeUna=c=>UNA_SC.find(x=>c<=x[0])[1];
const grossOf=p=>Object.entries(p.classi).reduce((a,[k,w])=>a+w/100*BF.ASS[k],0)/100;
/* menu */
(function(){const b=$('.burger'),n=$('nav.main');if(b)b.addEventListener('click',()=>{n.classList.toggle('open');b.setAttribute('aria-expanded',n.classList.contains('open'))})})();
/* grafici SVG */
function donut(classi,size=190){const R=size*.37,C=2*Math.PI*R,cx=size/2;let off=0;const tot=Object.values(classi).reduce((a,b)=>a+b,0)||1;
  const arcs=Object.entries(classi).filter(([,v])=>v>0).map(([k,v])=>{const l=v/tot*C,s=`<circle cx="${cx}" cy="${cx}" r="${R}" fill="none" stroke="${BF.COL[k]}" stroke-width="${size*.17}" stroke-dasharray="${l} ${C-l}" stroke-dashoffset="${-off}" transform="rotate(-90 ${cx} ${cx})"><title>${k} ${v}%</title></circle>`;off+=l;return s}).join('');
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img" aria-label="Composizione per classe di attivi"><circle cx="${cx}" cy="${cx}" r="${R}" fill="none" stroke="#E4EEE8" stroke-width="${size*.17}"/>${arcs}</svg>`}
function legend(classi){return `<div class="legend">${Object.entries(classi).filter(([,v])=>v>0).map(([k,v])=>`<span><i style="background:${BF.COL[k]}"></i>${k}<b>${v}%</b></span>`).join('')}</div>`}
const nice=m=>{const e=Math.pow(10,Math.floor(Math.log10(m))),f=m/e;return(f<=1?1:f<=2?2:f<=5?5:10)*e};
function axes(W,H,P,x0,x1,y0,y1,xl,yf){const sx=v=>P.l+(v-x0)/(x1-x0||1)*(W-P.l-P.r),sy=v=>H-P.b-(v-y0)/(y1-y0||1)*(H-P.t-P.b);
  const st=(y1-y0)/4;let g='';for(let i=0;i<=4;i++){const v=y0+st*i;g+=`<line x1="${P.l}" x2="${W-P.r}" y1="${sy(v)}" y2="${sy(v)}" stroke="#E4EEE8"/><text x="${P.l-8}" y="${sy(v)+4}" text-anchor="end">${yf(v)}</text>`}
  g+=xl.map(([v,t])=>`<text x="${sx(v)}" y="${H-8}" text-anchor="middle">${t}</text>`).join('');return{sx,sy,g}}
function lineChart(serie){ // serie: [[YYYY-MM-DD, valore]]
  const W=700,H=300,P={l:50,r:14,t:14,b:30},t=serie.map(s=>new Date(s[0]).getTime()),v=serie.map(s=>s[1]);
  const y0=Math.floor(Math.min(...v)/10)*10,y1=Math.ceil(Math.max(...v)/10)*10,x0=t[0],x1=t[t.length-1];
  const yrs=[];for(let y=new Date(x0).getFullYear()+1;y<=new Date(x1).getFullYear();y++)yrs.push([new Date(y+'-01-01').getTime(),String(y)]);
  const a=axes(W,H,P,x0,x1,y0,y1,yrs,x=>Math.round(x)),pts=serie.map((s,i)=>`${a.sx(t[i]).toFixed(1)},${a.sy(v[i]).toFixed(1)}`),
  area=`M${a.sx(x0)},${a.sy(y0)} L${pts.join(' L')} L${a.sx(x1)},${a.sy(y0)}Z`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Andamento storico del portafoglio, base 100">${a.g}<path d="${area}" fill="#2D4A3A" opacity=".08"/><polyline points="${pts.join(' ')}" fill="none" stroke="#2D4A3A" stroke-width="2.4" stroke-linejoin="round"/><circle cx="${a.sx(x1)}" cy="${a.sy(v[v.length-1])}" r="4.5" fill="#D18A1C"/></svg>`}
function fanChart(F){ // F: {anni, p10:[], p50:[], p90:[], versato:[]} valori annuali (indice 0..anni)
  const W=700,H=300,P={l:64,r:14,t:14,b:30},n=F.anni,ym=nice(Math.max(...F.p90)*1.02);
  const xl=[];const stp=n>20?5:n>10?2:1;for(let i=0;i<=n;i+=stp)xl.push([i,i+' a']);
  const a=axes(W,H,P,0,n,0,ym,xl,y=>y>=1000?(y/1000).toLocaleString('it-IT',{maximumFractionDigits:0})+' k':Math.round(y));
  const L=arr=>arr.map((y,i)=>`${a.sx(i).toFixed(1)},${a.sy(y).toFixed(1)}`),band=`M${L(F.p90).join(' L')} L${L(F.p10).reverse().join(' L')}Z`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Simulazione del valore dell'investimento nel tempo">${a.g}<path d="${band}" fill="#6C8EAD" opacity=".25"/><polyline points="${L(F.versato).join(' ')}" fill="none" stroke="#B8B07A" stroke-width="2" stroke-dasharray="6 5"/><polyline points="${L(F.p50).join(' ')}" fill="none" stroke="#2D4A3A" stroke-width="2.6"/><polyline points="${L(F.p10).join(' ')}" fill="none" stroke="#6C8EAD" stroke-width="1.5"/><polyline points="${L(F.p90).join(' ')}" fill="none" stroke="#6C8EAD" stroke-width="1.5"/></svg>`}
/* simulazione Monte Carlo: rendimento atteso = ipotesi per classe − TER − commissione di consulenza; volatilità del portafoglio */
function rng(s){return()=>{s|=0;s=s+0x6D2B79F5|0;let t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
function simula(p,init,mens,anni,vol,N=1500){
  const mu=grossOf(p)-p.ter/100,s=vol,m=anni*12,r=rng(20261104),mm=(Math.log(1+mu)-s*s/2)/12,sm=s/Math.sqrt(12);
  const yr=Array.from({length:anni+1},()=>[]);let fees=0;
  for(let k=0;k<N;k++){let V=init;yr[0].push(V);
    for(let i=1;i<=m;i++){const z=Math.sqrt(-2*Math.log(r()+1e-12))*Math.cos(2*Math.PI*r());V=V*Math.exp(mm+sm*z)+mens;if(i%12===0){V=Math.max(0,V-feeCont(V));yr[i/12].push(V)}}}
  const q=(a,f)=>{a.sort((x,y)=>x-y);return a[Math.floor(f*(a.length-1))]};
  return{anni,p10:yr.map(a=>q(a.slice(),.1)),p50:yr.map(a=>q(a.slice(),.5)),p90:yr.map(a=>q(a.slice(),.9)),versato:yr.map((_,i)=>init+mens*12*i),mu}}
/* dati storici (backtest) calcolati ogni giorno dal monitoraggio */
let STO=null;const stoP=fetch(BF.DATI,{cache:'no-store'}).then(r=>r.ok?r.json():null).then(j=>{STO=j}).catch(()=>{});
