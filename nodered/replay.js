// Closed-loop replay of the new DHW logic against historical prices and draws.
//
// The tank is SIMULATED, not replayed: historical temperature was produced by
// the old control, so feeding it back would never respond to the new decisions.
// Model: standing loss 0.15 K/h (measured), reheat 4.5 K/h (measured median),
// draws taken from the historical record at their observed times and sizes.
//
// Usage: node replay.js <price.csv> <draws.csv> <label> [--old]
const fs = require('fs');
const load = f => fs.readFileSync(f,'utf8').split('\n').map(l=>l.split(','))
  .filter(r=>r.length>=5 && /^20/.test(r[3]))
  .map(r=>({t:new Date(r[3]), v:parseFloat(r[4])})).filter(r=>!isNaN(r.v)).sort((a,b)=>a.t-b.t);
const loadDraws = f => fs.readFileSync(f,'utf8').trim().split('\n').filter(Boolean)
  .map(l=>{const [t,d]=l.split(','); return {t:new Date(t), d:parseFloat(d)};});

const [priceFile, drawFile, label, mode] = process.argv.slice(2);
const price = load(priceFile), draws = loadDraws(drawFile);
const OLD = mode === '--old';

const STANDING_LOSS = 0.15, REHEAT = 4.5;      // K/h, both measured
const ECO = 40, COMFORT = 55, ORDERED = 60;
// window must be long enough to actually complete the fill:
// evening 40->60 = 20 K at 4.5 K/h = 4.4 h ; morning 40->55 = 15 K = 3.3 h
const FILL_MIN_E = +(process.env.FILL_E||285), FILL_MIN_M = +(process.env.FILL_M||210);
const MORNING={h:6,m:30}, EVENING={h:17,m:0}, LOOKBACK_H = 18;
const PRICE_GATE_PCT=+(process.env.GATE||40), BLOCK_PCT=+(process.env.BLOCK||70), PRICE_FLOOR_TEMP=+(process.env.FLOOR||43), COMFORTABLE=+(process.env.COMF||48);

const sortedAll = price.map(p=>p.v).slice().sort((a,b)=>a-b);
const pctOf = v => 100*sortedAll.filter(x=>x<v).length/sortedAll.length;
function priceAt(t){let lo=0,hi=price.length-1,r=price[hi];
  while(lo<=hi){const m=(lo+hi)>>1; if(price[m].t<=t){r=price[m];lo=m+1}else hi=m-1} return r.v;}
const interval=(price[1].t-price[0].t)/60000;
const needE=Math.max(1,Math.round(FILL_MIN_E/interval)), needM=Math.max(1,Math.round(FILL_MIN_M/interval));
function cheapestBefore(deadline, need){
  const earliest=new Date(deadline.getTime()-LOOKBACK_H*3600e3); let best=null;
  for(let i=0;i+need<=price.length;i++){
    const s=price[i].t, e=new Date(price[i+need-1].t.getTime()+interval*60000);
    if(s<earliest||e>deadline) continue;
    let sum=0; for(let j=i;j<i+need;j++) sum+=price[j].v;
    const avg=sum/need; if(!best||avg<best.avg) best={s,e,avg};
  } return best;
}
const nextAt=(f,s)=>{const d=new Date(f); d.setHours(s.h,s.m,0,0); if(d<=f)d.setDate(d.getDate()+1); return d;};

// OLD logic: fixed bands 18:00->06:30 and 12:00->18:00, boost only, no price gate
function oldBands(t){
  const m=new Date(t); m.setHours(6,30,0,0); if(m<=t) m.setDate(m.getDate()+1);
  const e=new Date(t); e.setHours(18,0,0,0); if(e<=t) e.setDate(e.getDate()+1);
  const mStart=new Date(m.getTime()-12.5*3600e3), eStart=new Date(e.getTime()-6*3600e3);
  let bm=null,be=null;
  for(let i=0;i+needM<=price.length;i++){
    const s=price[i].t, en=new Date(price[i+needM-1].t.getTime()+interval*60000);
    let sum=0; for(let j=i;j<i+needM;j++) sum+=price[j].v; const avg=sum/needM;
    if(s>=mStart&&en<=m&&(!bm||avg<bm.avg)) bm={s,e:en,avg};
    if(s>=eStart&&en<=e&&(!be||avg<be.avg)) be={s,e:en,avg};
  } return {m:bm,e:be};
}

let T = 50, cost=0, kwh=0, belowFloor=0, steps=0, cmdPrices=[], blockedSteps=0;
const V_KWH_PER_K = 0.35;   // ~300 L tank; scales all kWh figures linearly, not the price result
let di=0, planDay=null, planM=null, planE=null;
const start=price[0].t, end=price[price.length-1].t;
for(let t=new Date(start); t<end; t=new Date(t.getTime()+15*60000)){
  steps++;
  const day=t.toDateString();
  if(day!==planDay){ planDay=day;
    if(OLD){const b=oldBands(t); planM=b.m; planE=b.e;}
    else {planM=cheapestBefore(nextAt(t,MORNING),needM); planE=cheapestBefore(nextAt(t,EVENING),needE);}
  }
  // apply draws due
  while(di<draws.length && draws[di].t<=t){ T-=draws[di].d; di++; }
  T-=STANDING_LOSS*0.25;
  const pp=pctOf(priceAt(t));
  const inW=w=>w&&t>=w.s&&t<=w.e;
  let setpoint=ECO;
  if([5,16].includes(t.getHours()) && T<46) setpoint=ORDERED;
  else if(T<38) setpoint=COMFORT;
  else if(inW(planE)) setpoint = OLD ? COMFORT : ((pp<=PRICE_GATE_PCT||T<PRICE_FLOOR_TEMP)?ORDERED:ECO);
  else if(inW(planM)) setpoint = OLD ? COMFORT : ((pp<=PRICE_GATE_PCT||T<PRICE_FLOOR_TEMP)?COMFORT:ECO);
  else if(!OLD && pp>=BLOCK_PCT && T>=COMFORTABLE){ setpoint=10; blockedSteps++; }
  if(T < setpoint-1){                       // pump runs
    const rise=Math.min(REHEAT*0.25, setpoint-T); T+=rise;
    const e=rise*V_KWH_PER_K; kwh+=e; cost+=e*priceAt(t); cmdPrices.push(priceAt(t));
  }
  if(T<40) belowFloor++;
}
const mean=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:0;
const flat=mean(price.map(p=>p.v));
console.log(`${label.padEnd(34)} ${OLD?'OLD':'NEW'}  ` +
  `kWh ${kwh.toFixed(0).padStart(4)}  avg price ${(cost/kwh).toFixed(3)}  ` +
  `vs flat ${(100*(flat-cost/kwh)/flat).toFixed(0).padStart(3)}%  ` +
  `cost EUR ${cost.toFixed(0).padStart(3)}  below40C ${(100*belowFloor/steps).toFixed(0)}%`);
