/* GROKBOT DESK - desk floor v3.1 (SAVIP live, 2026-10-21: monitor zoom + live alerts). Canvas scene, no external art: every object is drawn here.
   Logical room 720x414; static layer pre-rendered per view at device resolution (devicePixelRatio, max 3), dynamic layer per frame.
   Data: window.DeskFloor.set([{cv, d (desk dict from data.json savip.desks), idx, single}]). Coin logos = same-origin logos/*.webp. */
(function(){
var W=720,H=404,WB=160,MONO='ui-monospace,"SF Mono",Menlo,Consolas,monospace',SANS='-apple-system,"SF Pro Display","Helvetica Neue",Arial,sans-serif';
var GRN='#22e33a',RED='#ff4d2e';
function DPR(){return Math.min(3,window.devicePixelRatio||1)}
function A(hex,a){var n=parseInt(String(hex).slice(1),16);return'rgba('+(n>>16)+','+((n>>8)&255)+','+(n&255)+','+a+')'}
function SH(hex,f){var n=parseInt(String(hex).slice(1),16),r=n>>16,g=(n>>8)&255,b=n&255;if(f>=0){r+=(255-r)*f;g+=(255-g)*f;b+=(255-b)*f}else{r*=1+f;g*=1+f;b*=1+f}return'rgb('+(r|0)+','+(g|0)+','+(b|0)+')'}
function R(c,x,y,w,h,f){c.fillStyle=f;c.fillRect(x,y,w,h)}
function SR(c,x,y,w,h,s,lw){c.strokeStyle=s;c.lineWidth=lw||1;c.strokeRect(x+.5,y+.5,w-1,h-1)}
function RR(c,x,y,w,h,r){r=Math.min(r,w/2,h/2);c.beginPath();c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);c.arcTo(x,y+h,x,y,r);c.arcTo(x,y,x+w,y,r);c.closePath()}
function FR(c,x,y,w,h,r,f,s,lw){RR(c,x,y,w,h,r);if(f){c.fillStyle=f;c.fill()}if(s){c.strokeStyle=s;c.lineWidth=lw||1;c.stroke()}}
function P(c,pts,f,s,lw){c.beginPath();for(var i=0;i<pts.length;i++)i?c.lineTo(pts[i][0],pts[i][1]):c.moveTo(pts[i][0],pts[i][1]);c.closePath();if(f){c.fillStyle=f;c.fill()}if(s){c.strokeStyle=s;c.lineWidth=lw||1;c.stroke()}}
function L(c,x1,y1,x2,y2,s,lw){c.beginPath();c.moveTo(x1,y1);c.lineTo(x2,y2);c.strokeStyle=s;c.lineWidth=lw||1;c.stroke()}
function T(c,s,x,y,sz,col,al,wt,f){c.font=(wt||'700')+' '+sz+'px '+(f||MONO);c.fillStyle=col;c.textAlign=al||'left';c.textBaseline='alphabetic';c.fillText(s,x,y)}
function TW(c,s,sz,wt,f){c.font=(wt||'700')+' '+sz+'px '+(f||MONO);return c.measureText(s).width}
function E(c,x,y,rx,ry,f,rot){c.beginPath();c.ellipse(x,y,Math.max(.1,rx),Math.max(.1,ry),rot||0,0,6.2832);if(f){c.fillStyle=f;c.fill()}}
function hue(s){var h=0;s=String(s);for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))%360;return h}
function rnd(seed){var x=Math.abs(seed|0)%2147483647||7;return function(){x=x*16807%2147483647;return(x-1)/2147483646}}
function fmtP(v){if(v==null||!isFinite(v))return'';var a=Math.abs(v);return a>=1000?v.toFixed(0):a>=10?v.toFixed(2):a>=1?v.toFixed(3):a>=.01?v.toFixed(4):v.toPrecision(3)}
function pcs(p){return(p>=0?'+':'')+Number(p||0).toFixed(1)+'%'}
function usd(v){var a=Math.abs(v||0);return(v<0?'-':'')+'$'+(a>=1e6?(a/1e6).toFixed(2)+'M':a>=1e4?(a/1e3).toFixed(1)+'K':a.toFixed(2))}
/* ---------- images (same-origin logos/*.webp) ---------- */
var IM={},views=[];
function img(u){if(!u)return null;var o=IM[u];if(!o){o=IM[u]=new Image();o.decoding='async';o.onload=function(){o.ok=1;views.forEach(function(v){v.dirty=true})};o.onerror=function(){o.bad=1};o.src=u}return o.ok?o:null}
function coin(c,name,u,x,y,r,ring){var im=img(u);c.save();c.beginPath();c.arc(x,y,r,0,6.2832);c.closePath();
 if(im){c.save();c.clip();c.imageSmoothingEnabled=true;c.drawImage(im,x-r,y-r,2*r,2*r);c.restore()}
 else{var g=c.createLinearGradient(x,y-r,x,y+r);g.addColorStop(0,'hsl('+hue(name)+',70%,46%)');g.addColorStop(1,'hsl('+hue(name)+',70%,30%)');c.fillStyle=g;c.fill();
  T(c,String(name||'?').replace(/[^A-Za-z0-9$]/g,'').slice(0,2).toUpperCase(),x,y+r*.36,r*.95,'#fff','center','900',SANS)}
 if(ring){c.beginPath();c.arc(x,y,r,0,6.2832);c.strokeStyle=ring;c.lineWidth=Math.max(.8,r*.16);c.stroke()}c.restore()}
/* ---------- venue logos ---------- */
function logoK(c,k,x,y,s,th){c.save();
 if(k==='pill'||k==='pill2'){c.translate(x+s/2,y+s/2);c.rotate(-Math.PI/4);var w=s*.9,h=s*.4;
  c.save();c.shadowColor='rgba(0,0,0,.5)';c.shadowBlur=s*.12;c.shadowOffsetY=s*.05;RR(c,-w/2,-h/2,w,h,h/2);c.fillStyle='#f4f6f5';c.fill();c.restore();
  c.save();RR(c,-w/2,-h/2,w,h,h/2);c.clip();var g=c.createLinearGradient(0,-h/2,0,h/2);g.addColorStop(0,SH(th,.25));g.addColorStop(1,SH(th,-.25));R(c,-w/2,-h/2,w/2,h,g);
  R(c,-w/2,-h/2,w,h*.28,'rgba(255,255,255,.35)');c.restore();c.lineWidth=Math.max(.8,s/16);c.strokeStyle='#07120a';RR(c,-w/2,-h/2,w,h,h/2);c.stroke();L(c,0,-h/2,0,h/2,'#07120a',Math.max(.8,s/18))}
 else if(k==='alpaca'){FR(c,x,y,s,s,s*.24,'#f5c518');c.fillStyle='#111';c.beginPath();c.ellipse(x+s*.52,y+s*.58,s*.17,s*.24,0,0,6.3);c.fill();
  R(c,x+s*.40,y+s*.18,s*.08,s*.22,'#111');R(c,x+s*.56,y+s*.18,s*.08,s*.22,'#111');E(c,x+s*.47,y+s*.55,s*.03,s*.03,'#f5c518');E(c,x+s*.59,y+s*.55,s*.03,s*.03,'#f5c518')}
 else if(k==='btc'){var g2=c.createLinearGradient(x,y,x,y+s);g2.addColorStop(0,'#ffb347');g2.addColorStop(1,'#e07b00');c.beginPath();c.arc(x+s/2,y+s/2,s/2,0,6.3);c.fillStyle=g2;c.fill();
  T(c,'\u20bf',x+s/2,y+s*.73,s*.6,'#fff','center','900',SANS)}
 else{FR(c,x,y,s,s,s*.24,'#1d4ed8');var bw=s*.12;[.55,.3,.45,.2].forEach(function(t,i){R(c,x+s*(.17+i*.18),y+s*t,bw,s*(.82-t),'#fff')})}
 c.restore()}
/* ---------- props ---------- */
function plant(c,x,y,s,seed){var r=rnd(seed||7);
 E(c,x,y+16*s,11*s,2.6*s,'rgba(0,0,0,.45)');
 P(c,[[x-8*s,y+2*s],[x+8*s,y+2*s],[x+6*s,y+16*s],[x-6*s,y+16*s]],'#1c1f24');P(c,[[x-8*s,y+2*s],[x-2*s,y+2*s],[x-3*s,y+16*s],[x-6*s,y+16*s]],'#24282e');
 R(c,x-9*s,y,18*s,3*s,'#2c3138');E(c,x,y+1.2*s,7.6*s,1.4*s,'#0c0d0e');
 var n=16;for(var i=0;i<n;i++){var a=-Math.PI*(.04+.92*((i*7)%n)/(n-1))+(r()-.5)*.22,len=(14+r()*11)*s*(i%3?1:.8),wd=(3.4+r()*1.6)*s,
  bx=x+(r()-.5)*3*s,by=y,tx=bx+Math.cos(a)*len,ty=by+Math.sin(a)*len*1.05,mx=(bx+tx)/2,my=(by+ty)/2,nx=-Math.sin(a)*wd,ny=Math.cos(a)*wd,
  col=['#17652d','#1f8a3c','#2aa44a','#36bd59'][(i*3+(seed|0))%4];
  c.beginPath();c.moveTo(bx,by);c.quadraticCurveTo(mx+nx,my+ny,tx,ty);c.quadraticCurveTo(mx-nx,my-ny,bx,by);c.fillStyle=col;c.fill();
  L(c,bx,by,tx-(tx-bx)*.12,ty-(ty-by)*.12,'rgba(0,30,10,.45)',.5*s)}}
function banner(c,x,y,w,h,th,k){var cx=x+w/2;L(c,cx,y-14,x+2,y,'#3a3f46',.8);L(c,cx,y-14,x+w-2,y,'#3a3f46',.8);E(c,cx,y-14.5,1.3,1.3,'#5a6068');
 R(c,x-3,y-1.5,w+6,3,'#3a3f46');R(c,x-3,y-1.5,w+6,1,'#5a6068');
 var pts=[[x,y],[x+w,y],[x+w,y+h],[cx,y+h-w*.42],[x,y+h]];P(c,pts,'#0b1410');var g=c.createLinearGradient(x,0,x+w,0);g.addColorStop(0,'rgba(255,255,255,.04)');g.addColorStop(.5,'rgba(255,255,255,0)');g.addColorStop(1,'rgba(0,0,0,.25)');P(c,pts,g);
 P(c,pts,null,A(th,.85),1.2);P(c,[[x+2.5,y+2],[x+w-2.5,y+2],[x+w-2.5,y+h-3],[cx,y+h-w*.42-2.5],[x+2.5,y+h-3]],null,A(th,.3),.6);
 logoK(c,k,x+w*.18,y+h*.3,w*.64,th)}
function mon(c,x,y,w,h,th,kind,lab,val,data,seed){ // desk monitor with bezel + stand
 R(c,x+w/2-2,y+h,4,4,'#22262b');FR(c,x+w/2-8,y+h+3.5,16,2.5,1,'#2a2e34');
 FR(c,x,y,w,h,2,'#1b1f24',null);FR(c,x+.6,y+.6,w-1.2,h-1.2,2,null,'#30363d',.7);var sx=x+2,sy=y+2,sw=w-4,sh=h-4;R(c,sx,sy,sw,sh,'#04070a');
 var g=c.createLinearGradient(sx,sy,sx,sy+sh);g.addColorStop(0,A(th,.06));g.addColorStop(1,'rgba(0,0,0,0)');R(c,sx,sy,sw,sh,g);
 T(c,lab,sx+2,sy+4.6,3.4,'#7f8a94','left','800');if(val)T(c,val,sx+sw-2,sy+4.6,3.4,val.charAt(0)==='-'?RED:th,'right','800');
 var r=rnd(seed),px=sx+2,py=sy+7,pw=sw-4,ph=sh-9,i;
 if(kind===0){var s=data&&data.length>1?data:null;if(!s){s=[];var v=50;for(i=0;i<26;i++){v+=(r()-.45)*9;s.push(v)}}
  var lo=Math.min.apply(null,s),hi=Math.max.apply(null,s),rg=(hi-lo)||1,up=s[s.length-1]>=s[0],col=data?(up?GRN:RED):A(th,.95);
  c.beginPath();s.forEach(function(v,k){var X=px+k*pw/(s.length-1),Y=py+ph-(v-lo)/rg*ph*.9;k?c.lineTo(X,Y):c.moveTo(X,Y)});c.strokeStyle=col;c.lineWidth=.8;c.stroke();
  c.lineTo(px+pw,py+ph);c.lineTo(px,py+ph);c.closePath();var g2=c.createLinearGradient(0,py,0,py+ph);g2.addColorStop(0,A(col.charAt(0)==='#'?col:th,.3));g2.addColorStop(1,'rgba(0,0,0,0)');c.fillStyle=g2;c.fill()}
 else if(kind===1&&data&&data.v){var vv=data.v,vm=Math.max.apply(null,vv.map(function(q){return q[0]}))||1,n=vv.length;for(i=0;i<n;i++){var bh=Math.max(.6,ph*vv[i][0]/vm);R(c,px+i*pw/n+.2,py+ph-bh,Math.max(.5,pw/n-.5),bh,vv[i][1]?A(th,.85):A(RED,.8))}}
 else if(kind===2&&data&&data.h){var hh2=data.h,ma=Math.max.apply(null,hh2.map(Math.abs))||1,cols=10,rows=4;for(i=0;i<cols*rows;i++){var q2=hh2[hh2.length-cols*rows+i];var gx2=i%cols,gy2=Math.floor(i/cols);R(c,px+gx2*pw/cols+.3,py+gy2*ph/rows+.3,pw/cols-.6,ph/rows-.6,q2==null?'#0b1730':A(q2>=0?th:RED,.2+.75*Math.min(1,Math.abs(q2)/ma)))}}
 else if(kind===3&&data&&data.b){var bb=data.b,mb=Math.max.apply(null,bb.map(function(q){return Math.abs(q[1])}))||1,nb=Math.min(5,bb.length);for(i=0;i<nb;i++){R(c,px,py+i*ph/5+.4,Math.max(1,pw*Math.abs(bb[i][1])/mb),ph/5-1,bb[i][1]>=0?A(th,.85):A(RED,.85))}}
 else if(kind===1){var n=12;for(i=0;i<n;i++){var bh=ph*(.25+r()*.75);R(c,px+i*pw/n+.4,py+ph-bh,pw/n-.9,bh,r()>.25?A(th,.85):A(RED,.8))}}
 else if(kind===2){var cols=10,rows=4;for(var gy=0;gy<rows;gy++)for(var gx=0;gx<cols;gx++){var q=r();R(c,px+gx*pw/cols+.3,py+gy*ph/rows+.3,pw/cols-.6,ph/rows-.6,q>.8?A(th,.9):q>.55?A(th,.45):q>.3?'#10224a':'#0b1730')}}
 else if(kind===3){for(i=0;i<5;i++){var bw=pw*(.2+r()*.75);R(c,px,py+i*ph/5+.4,bw,ph/5-1,i%3===2?A(RED,.85):A(th,.85))}}
 R(c,sx,sy,sw,sh*.45,'rgba(255,255,255,.025)')}
function chair(c,x,y){E(c,x,y+15,11,2.4,'rgba(0,0,0,.5)');
 for(var i=0;i<5;i++){var a=i/5*6.2832+.3,ex=x+Math.cos(a)*9,ey=y+12+Math.sin(a)*2.6;L(c,x,y+12,ex,ey,'#22252a',1.4);E(c,ex,ey+1,1.2,1,'#0e0f11')}
 R(c,x-1,y+5,2,7,'#2a2d32');FR(c,x-10,y+1,20,5.5,2.5,'#16181c');FR(c,x-10,y+1,20,2,1,'#23262b');
 FR(c,x-9,y-13,18,14,4,'#131518');FR(c,x-7.5,y-11.5,15,10.5,3,'#1b1e22');L(c,x-6,y-11,x+5,y-11,'rgba(255,255,255,.08)',.7);
 FR(c,x-12,y-2,3,6,1,'#1d2024');FR(c,x+9,y-2,3,6,1,'#1d2024')}
function kb(c,x,y,w){FR(c,x,y,w,5,1,'#0d0f12');for(var r2=0;r2<3;r2++)for(var k=0;k<Math.floor(w/2.6);k++)R(c,x+1.2+k*2.6,y+.9+r2*1.35,1.8,.9,'#2a3038')}

/* ---------- monitor data + big monitor view (SAVIP v3) ---------- */
var KINDS=[0,1,2,3,1,0],LABS=[['TAPE','PNL'],['BOOK','FLOW'],['RISK','HEAT'],['FILLS','SIZE'],['FLOW','BOOK'],['PNL','TAPE']];
function monInfo(d,i,slot){var k=slot?(KINDS[i]+2)%4:KINDS[i],cs=d.candles||[],ms=d.mon||[],mn=d.mnames||[],j,o={k:k,lab:LABS[i][slot],key:'s'+i+(slot?'b':'a'),name:d.ticker,src:''};
 if(k===0){if(ms.length){j=(i+slot)%ms.length;o.s=ms[j];o.name=mn[j]||d.ticker;o.src='position price, last '+ms[j].length+' points'}else if(cs.length>1){o.s=cs.map(function(b){return b[3]});o.src='closes, '+cs.length+' candles'}}
 else if(k===1){if(cs.length>1){o.v=cs.slice(-24).map(function(b){return[b[4]||0,b[3]>=b[0]]});o.src='volume, last '+o.v.length+' candles'}}
 else if(k===2){if(cs.length>2){var r=[];for(j=1;j<cs.length;j++)r.push(cs[j-1][3]?(cs[j][3]/cs[j-1][3]-1)*100:0);o.h=r.slice(-40);o.src='candle returns, last '+o.h.length}}
 else{var hp=d.hp||[];if(hp.length){o.b=hp.slice(0,6);o.src=hp.length+' open positions'}else if(d.note!=='flat'&&d.ticker){o.b=[[d.ticker,d.pct]];o.src=d.note}}
 return o}
function monRects(){var L=[{key:'wall',x:WM.x-4,y:WM.y-4,w:WM.w+8,h:WM.h+8}];SL.forEach(function(s,i){L.push({key:'s'+i+'a',x:s[0]+9,y:s[1]-1,w:52,h:36},{key:'s'+i+'b',x:s[0]+63,y:s[1]+5,w:36,h:30})});return L}
var AXSKIP=null;function bigAxis(c,lo,hi,x,y,w,h,n){if(h<170)n=Math.min(n,3);for(var i=0;i<=n;i++){var yy=y+h*i/n;L(c,x,yy,x+w,yy,'rgba(255,255,255,.05)',1);if(AXSKIP==null||Math.abs(yy-AXSKIP)>13)T(c,fmtP(hi-(hi-lo)*i/n),x+w+6,yy+4,h<170?9:10,'#6b7580','left','600')}}
function drawBig(c,w,h,d,key,v){var th=d.theme||GRN,cs=d.candles||[],i;
 R(c,0,0,w,h,'#03050b');var g=c.createRadialGradient(w/2,h*.4,10,w/2,h*.4,w*.7);g.addColorStop(0,A(th,.07));g.addColorStop(1,'rgba(0,0,0,0)');R(c,0,0,w,h,g);
 var m=Math.max(8,Math.round(w*.012)),x=m,y=m,bw=w-2*m,bh=h-2*m;c.save();c.shadowColor=A(th,.45);c.shadowBlur=16;FR(c,x,y,bw,bh,10,'#0d1014');c.restore();FR(c,x,y,bw,bh,10,'#0d1014','#2c323a',1.2);
 var sx=x+6,sy=y+6,sw=bw-12,sh=bh-12;FR(c,sx,sy,sw,sh,6,'#020405');
 var info=key==='wall'?{k:'wall',lab:'MAIN SCREEN',name:d.ticker,src:(cs.length?cs.length+' candles':'no candles')}:monInfo(d,+key.charAt(1),key.charAt(2)==='b'?1:0);
 // title bar
 var tx=sx+12,ty=sy+12,big=Math.min(1.25,Math.max(.8,w/640));
 if(key==='wall'||info.k===0)coin(c,info.name,info.name===d.ticker?d.tlogo:null,tx+10,ty+10,10,null);
 var nx=(key==='wall'||info.k===0)?tx+26:tx;T(c,key==='wall'?(d.ticker||'—'):info.lab,nx,ty+9,15*big,'#f4f4f4','left','900',SANS);
 T(c,(key==='wall'?d.label+' desk \u00b7 '+d.venue+' \u00b7 '+(d.note==='open'?'live position':d.note==='flat'?'desk flat':'last closed trade'):d.label+' desk \u00b7 '+info.lab+' monitor \u00b7 '+(info.k===0?info.name+' \u00b7 ':'')+(info.src||'no data yet')),nx,ty+22,9.5*big,'#7c8690','left','600',SANS);
 var stats=key==='wall'?[['P&L',(d.pnl>=0?'+':'')+usd(d.pnl),d.pnl>=0],['CHANGE',pcs(d.pct),d.pct>=0],['VALUE',d.value?usd(d.value):'\u2014',null],['LAST',d.last!=null?fmtP(d.last):'\u2014',null],['OPEN',String(d.n_open),null],['DAY',String(d.day),null]]:[];
 if(info.k===0&&info.s&&info.s.length>1){var ch0=(info.s[info.s.length-1]/info.s[0]-1)*100;stats=[['LAST',fmtP(info.s[info.s.length-1]),null],['CHANGE',pcs(ch0),ch0>=0],['HIGH',fmtP(Math.max.apply(null,info.s)),null],['LOW',fmtP(Math.min.apply(null,info.s)),null]]}
 var nst=stats.length,show=Math.max(0,Math.min(nst,Math.floor((sw-230)/70))),bx0=sx+sw-12-show*70;
 for(i=0;i<show;i++){var bx=bx0+i*70;FR(c,bx,sy+9,64,30,4,'#0b0f13','#151b21',1);T(c,stats[i][0],bx+7,sy+20,8,'#68727c','left','800');T(c,stats[i][1].slice(0,10),bx+7,sy+33,11,stats[i][2]===true?GRN:stats[i][2]===false?RED:'#ececec','left','800')}
 L(c,sx,sy+46,sx+sw,sy+46,'#11161b',1);
 var cx=sx+10,cy=sy+58,cw=sw-74,chh=sh-58-34,vol=key==='wall'&&cs.length>1,vh=vol?Math.round(chh*.2):0,pch=chh-vh-(vol?8:0);
 v.dot=null;c.font='600 10px '+SANS;
 function empty(msg,sub){T(c,msg,sx+sw/2,cy+chh/2,18*big,A(th,.6),'center','900',SANS);if(sub)T(c,sub,sx+sw/2,cy+chh/2+20,10.5,'#56606a','center','600',SANS)}
 if(key==='wall'){
  if(cs.length<2)empty(d.note==='flat'?'FLAT \u00b7 no position':'waiting for candles',d.note==='flat'?'all cash \u00b7 rules decide the next buy':'');
  else{var lo=1e99,hi=-1e99,vm=0;cs.forEach(function(b){lo=Math.min(lo,b[2]);hi=Math.max(hi,b[1]);vm=Math.max(vm,b[4]||0)});var rg=(hi-lo)||Math.abs(hi)*.01||1;lo-=rg*.06;hi+=rg*.06;rg=hi-lo;
   AXSKIP=cy+pch*(1-(cs[cs.length-1][3]-lo)/rg);bigAxis(c,lo,hi,cx,cy,cw,pch,5);AXSKIP=null;var n=cs.length,cwid=cw/n,Y=function(q){return cy+pch*(1-(q-lo)/rg)};
   cs.forEach(function(b,k){var col=b[3]>=b[0]?GRN:RED,mx=cx+k*cwid+cwid/2;R(c,mx-.6,Y(b[1]),1.2,Math.max(1,Y(b[2])-Y(b[1])),col);var y1=Math.min(Y(b[0]),Y(b[3])),y2=Math.max(Y(b[0]),Y(b[3]));R(c,mx-cwid*.34,y1,Math.max(1.2,cwid*.68),Math.max(1.2,y2-y1),col);
    if(vol){var vv=vm>0?(b[4]||0)/vm:0;R(c,mx-cwid*.34,cy+chh-vv*vh,Math.max(1.2,cwid*.68),vv*vh,A(col,.5))}});
   if(vol)T(c,'VOL',cx+2,cy+pch+20,9,'#4f5963','left','800');
   var hk=0;cs.forEach(function(b,k){if(b[1]>cs[hk][1])hk=k});T(c,fmtP(cs[hk][1]),cx+hk*cwid+cwid/2,Y(cs[hk][1])-5,9.5,'#9aa3ab','center','700');
   var lb=cs[n-1],ly=Y(lb[3]),lc=lb[3]>=lb[0]?GRN:RED;c.setLineDash([3,3]);L(c,cx,ly,cx+cw,ly,A(lc,.6),1);c.setLineDash([]);FR(c,cx+cw+2,ly-8,62,16,3,lb[3]>=cs[0][0]?'#0f5a1c':'#6a1a10');T(c,fmtP(lb[3]),cx+cw+33,ly+4,10,'#fff','center','800');
   v.dot=[cx+(n-.5)*cwid,ly,lc]}}
 else if(info.k===0){var s=info.s;if(!s||s.length<2)empty('no series yet',d.note==='flat'?'desk flat \u00b7 nothing held':'');
  else{var lo2=Math.min.apply(null,s),hi2=Math.max.apply(null,s),r2=(hi2-lo2)||Math.abs(hi2)*.01||1;lo2-=r2*.08;hi2+=r2*.08;r2=hi2-lo2;bigAxis(c,lo2,hi2,cx,cy,cw,chh,5);
   var up=s[s.length-1]>=s[0],col=up?GRN:RED,X=function(k){return cx+k*cw/(s.length-1)},Yl=function(q){return cy+chh*(1-(q-lo2)/r2)};
   c.beginPath();s.forEach(function(q,k){k?c.lineTo(X(k),Yl(q)):c.moveTo(X(k),Yl(q))});c.lineTo(cx+cw,cy+chh);c.lineTo(cx,cy+chh);c.closePath();var gg=c.createLinearGradient(0,cy,0,cy+chh);gg.addColorStop(0,A(col,.28));gg.addColorStop(1,A(col,0));c.fillStyle=gg;c.fill();
   c.save();c.shadowColor=col;c.shadowBlur=10;c.beginPath();s.forEach(function(q,k){k?c.lineTo(X(k),Yl(q)):c.moveTo(X(k),Yl(q))});c.strokeStyle=col;c.lineWidth=2.2;c.lineJoin='round';c.stroke();c.restore();
   v.dot=[X(s.length-1),Yl(s[s.length-1]),col]}}
 else if(info.k===1){var vv2=info.v;if(!vv2)empty('no volume yet','');else{var vm2=Math.max.apply(null,vv2.map(function(q){return q[0]}))||1,nn=vv2.length,cw2=cw/nn;bigAxis(c,0,vm2,cx,cy,cw,chh,4);
   vv2.forEach(function(q,k){var hh3=chh*q[0]/vm2;FR(c,cx+k*cw2+cw2*.14,cy+chh-hh3,cw2*.72,Math.max(1,hh3),2,q[1]?A(th,.9):A(RED,.85))});if(h>300)T(c,'volume per candle \u00b7 green = up candle',cx+2,cy+chh+18,9.5,'#56606a','left','600',SANS)}}
 else if(info.k===2){var hv=info.h;if(!hv)empty('no candles yet','');else{var cols=10,rows=Math.ceil(hv.length/cols),ma=Math.max.apply(null,hv.map(Math.abs))||1,gw=cw/cols,gh=Math.min(chh/rows,gw*.62);
   hv.forEach(function(q,k){var gx=k%cols,gy=Math.floor(k/cols),X0=cx+gx*gw+2,Y0=cy+gy*gh+2;FR(c,X0,Y0,gw-4,gh-4,3,A(q>=0?th:RED,.18+.72*Math.min(1,Math.abs(q)/ma)));if(gw>34)T(c,(q>=0?'+':'')+q.toFixed(gw>60?2:1)+'%',X0+(gw-4)/2,Y0+(gh-4)/2+4,Math.min(11,gw/6),'#fff','center','800')});
   if(h>300)T(c,'return of each candle, oldest top-left \u00b7 brighter = bigger move',cx+2,cy+chh+18,9.5,'#56606a','left','600',SANS)}}
 else{var bb=info.b;if(!bb)empty('no positions',d.note==='flat'?'desk flat \u00b7 all cash':'');else{var mb=Math.max.apply(null,bb.map(function(q){return Math.abs(q[1])}))||1,nr=bb.length,rh=Math.min(34,chh/nr),lw=Math.min(120,cw*.24);
   bb.forEach(function(q,k){var Y0=cy+k*rh,bw2=(cw-lw-70)*Math.abs(q[1])/mb;T(c,q[0],cx,Y0+rh/2+4,12,'#e8e8e8','left','800',SANS);FR(c,cx+lw,Y0+rh*.2,Math.max(2,bw2),rh*.6,3,q[1]>=0?A(th,.85):A(RED,.85));T(c,pcs(q[1]),cx+lw+Math.max(2,bw2)+8,Y0+rh/2+4,11,q[1]>=0?GRN:RED,'left','800')});
   if(h>300)T(c,'unrealised P&L per open position',cx+2,cy+chh+18,9.5,'#56606a','left','600',SANS)}}
 T(c,d.label+' DESK \u00b7 '+(key==='wall'?'MAIN SCREEN':info.lab)+' \u00b7 '+d.ticker+' '+pcs(d.pct),sx+sw/2,sy+sh-8,10*big,A(th,.9),'center','800');
 var gl=c.createLinearGradient(0,sy,0,sy+sh);gl.addColorStop(0,'rgba(255,255,255,.03)');gl.addColorStop(.35,'rgba(255,255,255,0)');R(c,sx,sy,sw,sh,gl)}
function dynBig(c,w,h,d,v,t){if(v.dot){c.save();var p=.5+.5*Math.sin(t*4);c.shadowColor=v.dot[2];c.shadowBlur=14;E(c,v.dot[0],v.dot[1],4,4,v.dot[2]);c.globalAlpha=.35*(1-p);E(c,v.dot[0],v.dot[1],5+p*9,5+p*9,v.dot[2]);c.restore()}
 var m=Math.max(8,Math.round(w*.012))+6;R(c,m,m+((t*40)%(h-2*m)),w-2*m,1.5,'rgba(255,255,255,.025)');
 c.globalAlpha=.6+.4*Math.sin(t*3);E(c,w-m-14,h-m-12,3,3,GRN);c.globalAlpha=1;T(c,'LIVE',w-m-22,h-m-8.5,9,'#9aa3ab','right','800',SANS)}
function station(c,x,y,i,d,th){ // one trading desk: 2 monitors, desk, keyboard, mouse, mug, chair
 E(c,x+52,y+56,62,5,'rgba(0,0,0,.35)');
 var ms=(d.mon||[]),s=ms.length?ms[i%ms.length]:null,kinds=[0,1,2,3,1,0],labs=[['TAPE','PNL'],['BOOK','FLOW'],['RISK','HEAT'],['FILLS','SIZE'],['FLOW','BOOK'],['PNL','TAPE']][i],
  v1=s&&s.length>1?((s[s.length-1]/s[0]-1)*100):null;
 var m1=monInfo(d,i,0),m2=monInfo(d,i,1);
 mon(c,x+10,y,50,30,th,m1.k,m1.lab,m1.s&&m1.s.length>1?pcs((m1.s[m1.s.length-1]/m1.s[0]-1)*100):'',m1.k===0?m1.s:m1,hue(d.label)+i*97);
 mon(c,x+64,y+6,34,24,th,m2.k,m2.lab,'',m2.k===0?m2.s:m2,hue(d.label)+i*31+5);
 P(c,[[x,y+36],[x+104,y+36],[x+109,y+46],[x-5,y+46]],'#2a2e35');L(c,x,y+36.4,x+104,y+36.4,'rgba(255,255,255,.12)',.7);
 R(c,x-5,y+46,114,7,'#15181c');R(c,x-5,y+46,114,1,'#3a3f47');R(c,x-5,y+52.4,114,.8,A(th,.25));
 P(c,[[x-5,y+46],[x,y+46],[x,y+68],[x-5,y+68]],'#121418');P(c,[[x+104,y+46],[x+109,y+46],[x+109,y+68],[x+104,y+68]],'#121418');L(c,x-4.5,y+46,x-4.5,y+68,'#3a3f47',.7);L(c,x+108.5,y+46,x+108.5,y+68,'#2a2e35',.7);R(c,x,y+53,104,6,'#0c0e11');
 kb(c,x+24,y+39,34);E(c,x+66,y+41.5,2.2,1.5,'#cfd5db');E(c,x+66,y+41,1.8,1,'#eef1f4');
 FR(c,x+86,y+38,5,5,1,'#e6e6e6');R(c,x+86.6,y+39,3.8,1.2,A(th,.9));c.beginPath();c.arc(x+92,y+40.5,1.6,-1.4,1.4);c.strokeStyle='#e6e6e6';c.lineWidth=.8;c.stroke();
 if(i%2===0){FR(c,x+4,y+38.5,12,5,.8,'#f2f2f2');R(c,x+5,y+39.4,10,.6,'#bbb');R(c,x+5,y+40.8,8,.6,'#bbb')}
 chair(c,x+41,y+70)}
function sofa(c,x,y,w,th){P(c,[[x-14,y+30],[x+w+14,y+30],[x+w+26,y+58],[x-26,y+58]],A(th,.07));P(c,[[x-14,y+30],[x+w+14,y+30],[x+w+26,y+58],[x-26,y+58]],null,A(th,.22),.8);
 P(c,[[x-8,y+33],[x+w+8,y+33],[x+w+16,y+54],[x-16,y+54]],null,A(th,.12),.6);
 E(c,x+w/2,y+31,w/2+8,4,'rgba(0,0,0,.5)');
 FR(c,x,y,w,14,3,'#121418');for(var k=0;k<3;k++){FR(c,x+3+k*(w-6)/3,y+2,(w-6)/3-2,11,3,'#1a1d21');L(c,x+6+k*(w-6)/3,y+3,x+(k+1)*(w-6)/3-2,y+3,'rgba(255,255,255,.07)',.7)}
 FR(c,x-2,y+12,w+4,10,2,'#16181c');for(k=0;k<3;k++){FR(c,x+2+k*(w-4)/3,y+12.5,(w-4)/3-1.5,7,2,'#1e2125');L(c,x+4+k*(w-4)/3,y+13.2,x+(k+1)*(w-4)/3-3,y+13.2,'rgba(255,255,255,.06)',.6)}
 FR(c,x-9,y+4,9,21,3,'#141619');FR(c,x+w,y+4,9,21,3,'#141619');R(c,x-9,y+5,9,1,'rgba(255,255,255,.07)');R(c,x+w,y+5,9,1,'rgba(255,255,255,.07)');
 R(c,x-2,y+22,w+4,4,'#0d0e10');R(c,x+2,y+26,3,3,'#0a0b0c');R(c,x+w-5,y+26,3,3,'#0a0b0c')}
function laptop(c,x,y,th,k){P(c,[[x,y+9],[x+24,y+9],[x+27,y+13],[x-3,y+13]],'#9aa1a8');P(c,[[x,y+9],[x+24,y+9],[x+25,y+10.5],[x-1,y+10.5]],'#c4cad0');
 P(c,[[x+1,y-6],[x+23,y-6],[x+24,y+9],[x,y+9]],'#2b3036');P(c,[[x+2.4,y-4.6],[x+21.6,y-4.6],[x+22.4,y+7.8],[x+1.6,y+7.8]],'#05080b');
 c.save();c.shadowColor=th;c.shadowBlur=5;logoK(c,k,x+8,y-2.4,8,th);c.restore()}
function table(c,x,y,w,th,k){E(c,x+w/2,y+18,w/2+4,3,'rgba(0,0,0,.5)');P(c,[[x+4,y],[x+w-4,y],[x+w,y+6],[x,y+6]],'#24282e');R(c,x,y+6,w,5,'#131518');R(c,x,y+6,w,.8,'#3a3f46');
 R(c,x+3,y+11,3,6,'#0e1012');R(c,x+w-6,y+11,3,6,'#0e1012');laptop(c,x+w*.55,y-11,th,k);plant(c,x+w*.22,y-8,.36,4)}
function rack(c,x,y,w,h,th,k,venue){E(c,x+w/2,y+h+2,w/2+6,3,'rgba(0,0,0,.5)');P(c,[[x,y],[x+w,y],[x+w+5,y-5],[x+5,y-5]],'#1d2126');P(c,[[x+w,y],[x+w+5,y-5],[x+w+5,y+h-5],[x+w,y+h]],'#0b0d10');
 R(c,x,y,w,h,'#101317');SR(c,x,y,w,h,'#2a3037',1);R(c,x+1,y+1,1,h-2,'rgba(255,255,255,.06)');
 FR(c,x+5,y+5,w-10,20,2,'#07090b',A(th,.35),.6);logoK(c,k,x+w/2-5,y+7,10,th);T(c,venue,x+w/2,y+23,4,'#e6e6e6','center','800',SANS);
 for(var i=0;i<9;i++){var uy=y+30+i*((h-36)/9);FR(c,x+4,uy,w-8,(h-36)/9-2.4,1,'#0b0e11','#20262c',.6);for(var v=0;v<5;v++)R(c,x+w-17+v*2.2,uy+2,1.2,(h-36)/9-6.5,'#161b20')}}
function pedestal(c,x,y,w,h,label,th){E(c,x+w/2,y+h+2,w/2+5,3,'rgba(0,0,0,.5)');P(c,[[x+4,y],[x+w-4,y],[x+w,y+6],[x,y+6]],'#23272d');R(c,x,y+6,w,h-6,'#121518');R(c,x,y+6,w,.8,'#3b4048');
 FR(c,x+5,y+h-13,w-10,9,1.5,'#07090b','#3a4048',.7);T(c,label,x+w/2+4,y+h-6.6,4.6,'#e6e6e6','center','800',SANS);if(PL_K)logoK(c,PL_K,x+8,y+h-11.5,6,PL_T)}var PL_K=null,PL_T='#22e33a';
function dishS(c,x,y,th){R(c,x-2,y-6,4,14,'#3c434b');E(c,x,y+8,8,2.4,'#2a2f35');
 c.save();c.translate(x,y-14);c.rotate(-.55);var g=c.createRadialGradient(-3,-3,2,0,0,18);g.addColorStop(0,'#5d666f');g.addColorStop(1,'#2a3036');E(c,0,0,18,10,g);E(c,0,0,18,10,null);c.strokeStyle='#8a939b';c.lineWidth=.9;c.stroke();
 for(var i=1;i<4;i++){E(c,0,0,18*i/4,10*i/4,null);c.strokeStyle='rgba(200,210,220,.25)';c.lineWidth=.5;c.stroke()}
 for(i=0;i<6;i++){var a=i/6*6.2832;L(c,0,0,Math.cos(a)*18,Math.sin(a)*10,'rgba(200,210,220,.2)',.5)}
 L(c,0,0,0,-14,'#aab3bb',1);E(c,0,-15,2,2,A(th,1));c.restore()}
function shelfL(c,x,y,d,th){ // cabinet with coin figurines (real coins)
 E(c,x+31,y+52,36,4,'rgba(0,0,0,.45)');P(c,[[x+3,y],[x+59,y],[x+62,y+5],[x,y+5]],'#262a30');R(c,x,y+5,62,45,'#121418');R(c,x,y+5,62,.8,'#3b4048');SR(c,x,y+5,62,45,'#23272d',.8);
 R(c,x+4,y+9,24,37,'#090b0d');R(c,x+4,y+27,24,1.4,'#23272d');plant(c,x+15,y+13,.28,9);[0,1,2].forEach(function(k){FR(c,x+8+k*5,y+33,3,11,1,'#d8dde2')});
 FR(c,x+32,y+9,26,37,2,'#0d0f12','#2a2f35',.8);E(c,x+52,y+27,1.6,1.6,'#555c64');logoK(c,d.logo,x+38,y+21,13,th);
 var cs=(d.coins||[]).slice(0,4),lg=d.clogos||[];
 for(var k=0;k<4;k++){var fx=x+9+k*14.6,fy=y-8.5;FR(c,fx-5.5,fy+6.5,11,2.6,1,'#2c3137');if(cs[k])coin(c,cs[k],lg[k],fx,fy,6.8,'#e8e8e8');else{E(c,fx,fy,6,6.8,'#2a2f35');E(c,fx-2,fy-1,1.1,1.3,'#0b0b0b');E(c,fx+2,fy-1,1.1,1.3,'#0b0b0b')}}}
function paperBin(c,x,y,d,th){E(c,x+23,y+58,27,3.5,'rgba(0,0,0,.5)');P(c,[[x+2,y],[x+44,y],[x+47,y+6],[x-1,y+6]],'#262a30');R(c,x+6,y+1.5,34,3.4,'#0a0b0c');
 var r=rnd(11);for(var i=0;i<14;i++){var px=x+8+r()*30;L(c,px,y+3.4,px+(r()-.5)*4,y-1-r()*5,'#e9ecef',.7)}
 R(c,x-1,y+6,48,50,'#111316');R(c,x-1,y+6,48,.8,'#3b4048');SR(c,x-1,y+6,48,50,'#22262c',.8);logoK(c,d.logo,x+15,y+16,16,th);
 T(c,d.venue,x+23,y+41,6,'#f0f0f0','center','800',SANS);T(c,'PAPER ONLY',x+23,y+50,3.8,'#8a939c','center','800')}
function sideWall(c,d,th){P(c,[[0,0],[64,0],[64,WB],[0,WB+64]],'#080a0d');var g=c.createLinearGradient(0,0,64,0);g.addColorStop(0,'rgba(0,0,0,.5)');g.addColorStop(1,'rgba(255,255,255,.015)');P(c,[[0,0],[64,0],[64,WB],[0,WB+64]],g);
 L(c,64,0,64,WB,'#1b1f24',1.2);L(c,64,WB,0,WB+64,A(th,.25),1);
 var X0=8,X1=56;function wy(x,y){return y+(64-x)/64*(y/WB)*64}
 var q=[[X1,wy(X1,52)],[X1,wy(X1,140)],[X0,wy(X0,140)],[X0,wy(X0,52)]];q=[[X0,wy(X0,40)],[X1,wy(X1,40)],[X1,wy(X1,138)],[X0,wy(X0,138)]];
 P(c,[[q[0][0]-2,q[0][1]-2],[q[1][0]+2,q[1][1]-2],[q[2][0]+2,q[2][1]+2],[q[3][0]-2,q[3][1]+2]],'#1b1f24');P(c,q,'#030506');P(c,q,null,A(th,.35),.8);
 var r=rnd(hue(d.label)+5),v=.5;for(var i=0;i<10;i++){var bx=X0+3+i*4.4,top0=60+r()*30+(i<5?0:-(i-5)*5),len=6+r()*14;v=r()>.42;var a=wy(bx,top0),b=wy(bx,top0+len);R(c,bx,a,2.4,b-a,v?GRN:RED);L(c,bx+1.2,a-3,bx+1.2,b+3,v?GRN:RED,.4)}
 for(var gy=0;gy<5;gy++)for(var gx=0;gx<8;gx++){var cx=X0+3+gx*5.6,cy=wy(cx,108+gy*5.6),cy2=wy(cx,108+gy*5.6+4.4),qq=r();R(c,cx,cy,4.6,cy2-cy,qq>.55?A(GRN,.85):qq>.3?A(RED,.8):'#0e1a10')}}
/* ---------- wall monitor ---------- */
var WM={x:186,y:20,w:314,h:132};
function wallMon(c,d,th){var x=WM.x,y=WM.y,w=WM.w,h=WM.h;
 c.save();c.shadowColor=A(th,.5);c.shadowBlur=7;FR(c,x-4,y-4,w+8,h+8,4,'#0b0d10');c.restore();FR(c,x-4,y-4,w+8,h+8,4,'#15191e','#2c323a',1.2);L(c,x-3,y+h+4,x+w+3,y+h+4,A(th,.55),1);FR(c,x-1.5,y-1.5,w+3,h+3,3,null,'#2a3037',.7);
 R(c,x,y,w,h,'#020405');
 var pc=pcs(d.pct),up=d.pct>=0,cs=d.candles||[];
 coin(c,d.ticker,d.tlogo,x+9,y+9,5.5,null);T(c,d.ticker,x+17,y+8.6,6.4,'#f2f2f2','left','900',SANS);T(c,d.label+' desk \u00b7 '+d.venue+(d.note==='open'?' \u00b7 open':' \u00b7 '+d.note),x+17,y+14.4,3.6,'#7c8690','left','700');
 var st=[['P&L',(d.pnl>=0?'+':'')+usd(d.pnl),up],['CHANGE',pc,up],['VALUE',d.value?usd(d.value):'\u2014',null],['LAST',d.last!=null?fmtP(d.last):'\u2014',null],['OPEN',String(d.n_open),null],['DAY',String(d.day),null]];
 st.forEach(function(s,k){var bx=x+92+k*37;FR(c,bx,y+3,35,13,1.5,'#0b0f13');T(c,s[0],bx+2.5,y+7.4,3.2,'#68727c','left','800');T(c,s[1].slice(0,9),bx+2.5,y+13.4,4.6,s[2]===true?GRN:s[2]===false?RED:'#e8e8e8','left','800')});
 L(c,x,y+18.5,x+w,y+18.5,'#11161b',.7);
 T(c,(d.ck&&d.ck.indexOf('a_')===0?'1D':'5m')+' \u00b7 '+d.ticker+' \u00b7 '+(cs.length?cs.length+' candles':'no candles')+' \u00b7 '+(d.note==='open'?'live position':d.note==='flat'?'desk flat':'last closed trade'),x+4,y+24,3.4,'#5f6973','left','700');
 var cx=x+4,cy=y+28,cw=w-34,ch=78,vy=cy+ch+3,vh=16;
 c.strokeStyle='rgba(255,255,255,.045)';c.lineWidth=.6;for(var i=1;i<5;i++){L(c,cx,cy+ch*i/5,cx+cw,cy+ch*i/5,'rgba(255,255,255,.045)',.6)}for(i=1;i<8;i++)L(c,cx+cw*i/8,cy,cx+cw*i/8,vy+vh,'rgba(255,255,255,.03)',.6);
 if(cs.length<2){T(c,d.note==='flat'?'FLAT \u00b7 no position':'waiting for candles',cx+cw/2,cy+ch/2+2,10,d.note==='flat'?A(th,.65):'#3a3f44','center','900',SANS);
  if(d.note==='flat')T(c,'all cash \u00b7 rules decide the next buy',cx+cw/2,cy+ch/2+13,5,'#56606a','center','700');}
 else{var lo=1e99,hi=-1e99,vmax=0;cs.forEach(function(b){lo=Math.min(lo,b[2]);hi=Math.max(hi,b[1]);vmax=Math.max(vmax,b[4]||0)});var rg=(hi-lo)||Math.abs(hi)*.01||1;lo-=rg*.06;hi+=rg*.06;rg=hi-lo;
  var n=cs.length,bw=cw/n,Y=function(v){return cy+ch*(1-(v-lo)/rg)};
  cs.forEach(function(b,k){var o=b[0],hh=b[1],l=b[2],cl=b[3],col=cl>=o?GRN:RED,mx=cx+k*bw+bw/2;R(c,mx-.35,Y(hh),.7,Math.max(.7,Y(l)-Y(hh)),col);
   var y1=Math.min(Y(o),Y(cl)),y2=Math.max(Y(o),Y(cl));R(c,mx-bw*.33,y1,Math.max(.8,bw*.66),Math.max(.8,y2-y1),col);
   var vv=vmax>0?(b[4]||0)/vmax:(.2+((k*37)%11)/14);R(c,mx-bw*.33,vy+vh-vv*vh,Math.max(.8,bw*.66),vv*vh,A(col,.55))});
  var hiK=0,loK=0;cs.forEach(function(b,k){if(b[1]>cs[hiK][1])hiK=k;if(b[2]<cs[loK][2])loK=k});
  var hx=cx+hiK*bw+bw/2;T(c,fmtP(cs[hiK][1]),hx,Y(cs[hiK][1])-2.5,3.4,'#9aa3ab','center','700');
  for(i=0;i<=4;i++){var pv=hi-rg*i/4;T(c,fmtP(pv),x+w-3,cy+ch*i/4+1.5,3.3,'#5f6973','right','700')}
  var lc=cs[n-1][3],ly=Y(lc);c.setLineDash([2,2]);L(c,cx,ly,cx+cw,ly,A(lc>=cs[n-1][0]?GRN:RED,.6),.6);c.setLineDash([]);
  FR(c,x+w-29,ly-3.6,27,7,1,lc>=cs[0][0]?'#0f5a1c':'#6a1a10');T(c,fmtP(lc),x+w-15.5,ly+1.5,3.6,'#fff','center','800')}
 T(c,'VOL',cx+1,vy+4,3,'#4f5963','left','800');
 var gl=c.createLinearGradient(0,y,0,y+h);gl.addColorStop(0,'rgba(255,255,255,.035)');gl.addColorStop(.4,'rgba(255,255,255,0)');R(c,x,y,w,h,gl);
 T(c,d.label+' DESK \u00b7 '+d.ticker+' '+pc+(d.note==='open'?' TODAY':d.note==='flat'?' \u00b7 ALL CASH':' \u00b7 LAST TRADE'),x+w/2,y+h+14,6.4,A(th,.95),'center','800')}
/* ---------- the room (static layer) ---------- */
function drawStatic(c,d){var th=d.theme,i;
 R(c,0,0,W,H,'#05070a');
 var gw=c.createLinearGradient(0,0,0,WB);gw.addColorStop(0,'#07090c');gw.addColorStop(1,'#0e1217');R(c,0,0,W,WB,gw);
 for(i=64;i<W;i+=56){R(c,i,0,1,WB-6,'#0b0e12');R(c,i+1,0,.6,WB-6,'rgba(255,255,255,.018)')}
 R(c,0,WB-6,W,6,'#0b0e12');R(c,0,WB-6,W,.8,'#1c2127');R(c,0,WB,W,1,A(th,.12));
 var gf=c.createLinearGradient(0,WB,0,H);gf.addColorStop(0,'#090d16');gf.addColorStop(1,'#05070c');R(c,0,WB,W,H-WB,gf);
 c.save();c.beginPath();c.rect(0,WB+1,W,H-WB);c.clip();var vx=W/2+20,vy=-320;
 for(i=-14;i<=26;i++){var fx=vx+(i-6)*58;var t1=(WB-vy)/(H-vy);L(c,vx+(fx-vx)*t1,WB,fx,H,'rgba(110,140,210,.045)',.7)}
 for(i=1;i<14;i++){var yy=WB+(H-WB)*Math.pow(i/14,1.55);L(c,0,yy,W,yy,'rgba(110,140,210,.04)',.7)}c.restore();
 var fg=c.createRadialGradient(W/2,WB+40,10,W/2,WB+40,330);fg.addColorStop(0,A(th,.045));fg.addColorStop(1,'rgba(0,0,0,0)');R(c,0,WB,W,H-WB,fg);
 var wg=c.createRadialGradient(343,86,20,343,86,240);wg.addColorStop(0,A(th,.07));wg.addColorStop(1,'rgba(0,0,0,0)');R(c,0,0,W,WB,wg);
 sideWall(c,d,th);L(c,700,WB,720,WB+26,'#1b1f24',1);
 c.save();c.shadowColor='rgba(0,0,0,.7)';c.shadowBlur=8;FR(c,74,10,62,60,11,'#111317');c.restore();FR(c,74,10,62,60,11,null,'#1d2026',.8);logoK(c,d.logo,86,21,38,th);
 if(d.logo==='pill'||d.logo==='pill2')T(c,d.venue,105,89,d.venue.length>8?11.5:14,'#f4f4f4','center','800',SANS);else{T(c,d.title.replace(' FLOOR',''),105,84,7.4,'#f0f0f0','center','800',SANS);T(c,'FLOOR',105,93,7.4,'#f0f0f0','center','800',SANS)}
 banner(c,142,28,34,92,th,d.logo);banner(c,514,44,30,86,th,d.logo);banner(c,612,62,22,60,th,d.logo);
 wallMon(c,d,th);
 var cn=(d.coins||[]).slice(0,6),cl=d.clogos||[];for(i=0;i<6;i++){var ccx=552+i*30,ccy=26;E(c,ccx,ccy+2,14.5,14.5,'rgba(0,0,0,.55)');c.beginPath();c.arc(ccx,ccy,13.6,0,6.3);c.fillStyle='#e9e9e9';c.fill();
  if(cn[i])coin(c,cn[i],cl[i],ccx,ccy,11.6,null);else{c.beginPath();c.arc(ccx,ccy,11.6,0,6.3);c.fillStyle='#0b0d10';c.fill();logoK(c,d.logo,ccx-7.5,ccy-7.5,15,th)}}
 FR(c,550,60,58,34,2,'#05080a','#30363e',1.2);FR(c,552.5,62.5,53,29,1.5,null,'#15191e',.6);
 FR(c,551,98,56,11,1.5,'#0d1013','#30363e',.8);T(c,'LOCAL TIME',579,105.6,5.2,'#e6ebef','center','800',SANS);
 FR(c,644,56,74,66,2,'#07090b','#2b3138',1);R(c,646,58,70,1,'rgba(255,255,255,.05)');T(c,'DAY '+d.day+' \u00b7 '+(d.rules||[]).length+' RULES',649,66,4.8,'#f0f0f0','left','800');
 c.save();c.beginPath();c.rect(645,68,72,52);c.clip();(d.rules||[]).forEach(function(r,k){T(c,'- '+String(r).toUpperCase().slice(0,24),649,76+k*7.6,3.5,['#ffd166','#ff9f43','#ffd166','#ff6b5a','#ffd166','#ff6b5a'][k%6],'left','700')});c.restore();
 plant(c,164,134,.82,3);plant(c,701,140,.92,5);
 var hx=556,hy=150;E(c,hx+58,hy+30,66,4.5,'rgba(0,0,0,.45)');headDesk(c,th);R(c,hx-3,hy+22,5,12,'#101215');R(c,hx+114,hy+22,5,12,'#101215');
 mon(c,hx+6,hy-18,24,16,th,1,'BOOK','',null,hue(d.label)+77);FR(c,hx+96,hy-6,14,7,1.5,'#24282e');FR(c,hx+97,hy-9,12,3.4,1.5,'#2f343b');for(i=0;i<6;i++)R(c,hx+98.5+(i%3)*3.2,hy-4.8+Math.floor(i/3)*2.4,2,1.4,'#6b737c');
 for(i=0;i<4;i++)FR(c,hx+80,hy-3-i*1.4,12,2.4,.5,i%2?'#dcdcdc':'#f4f4f4');
 shelfL(c,66,196,d,th);paperBin(c,16,300,d,th);
 for(i=0;i<6;i++)station(c,SL[i][0],SL[i][1],i,d,th);
 PL_K=d.logo;PL_T=th;pedestal(c,566,236,58,34,'TOP RUNNER',th);pedestal(c,562,334,66,34,'WHALE RADAR',th);
 E(c,595,258,0,0);rack(c,652,198,48,150,th,d.logo,d.venue);
 plant(c,254,368,.95,1);plant(c,452,366,.95,2);plant(c,44,262,.8,6);plant(c,520,170,.7,8);
 sofa(c,288,338,124,th);table(c,302,384,96,th,d.logo);
 var vg=c.createRadialGradient(W/2,H/2,H*.45,W/2,H/2,W*.62);vg.addColorStop(0,'rgba(0,0,0,0)');vg.addColorStop(1,'rgba(0,0,0,.45)');R(c,0,0,W,H,vg)}
function headDesk(c,th){var hx=556,hy=150;P(c,[[hx,hy],[hx+116,hy],[hx+121,hy+9],[hx-5,hy+9]],'#2a2e35');L(c,hx,hy+.4,hx+116,hy+.4,'rgba(255,255,255,.12)',.7);
 R(c,hx-5,hy+9,126,13,'#14171b');R(c,hx-5,hy+9,126,.9,'#3a3f47');T(c,'HEAD OF THE FLOOR',hx+60,hy+18,4.8,'#e8c55a','center','800')}
var SL=[[150,176],[278,176],[406,176],[150,258],[278,258],[406,258]];
/* ---------- characters ---------- */
var BOT={SCAN:['#2dd4bf','blob'],JUDGE:['#a78bfa','star'],SIZE:['#e9edf1','round'],FILLS:['#ff7a1a','square'],RISK:['#34d058','blob'],QUANT:['#818cf8','drop'],
 CHIEF:['#f4f6f8','ghost'],TREND:['#f5c518','blob'],STOCKS:['#38bdf8','square'],CRYPTO:['#f59e0b','star'],VET:['#c47a45','blob']};
function eyes(c,x,y,s,blink,look){var ex=2.6*s,ey=y-.4*s;if(blink){L(c,x-ex-1.1*s,ey,x-ex+1.1*s,ey,'#0a0a0a',.9*s);L(c,x+ex-1.1*s,ey,x+ex+1.1*s,ey,'#0a0a0a',.9*s);return}
 E(c,x-ex+look,ey,1.25*s,1.7*s,'#0a0a0a');E(c,x+ex+look,ey,1.25*s,1.7*s,'#0a0a0a');E(c,x-ex+look+.45*s,ey-.6*s,.42*s,.5*s,'#fff');E(c,x+ex+look+.45*s,ey-.6*s,.42*s,.5*s,'#fff')}
function bot(c,name,x,y,s,t,k,walk){var cfg=BOT[name]||['#9ca3af','blob'],col=cfg[0],typ=cfg[1],ph=t*2.2+k*1.7,bob=Math.sin(ph)*1.1*s,sq=1+Math.sin(ph)*.035;
 var bl=((t+k*1.31)%(3.4+k*.37))<.14,look=Math.sin(t*.7+k)*.5*s;
 E(c,x,y+6.4*s,6*s*(1-bob/(10*s)),1.4*s,'rgba(0,0,0,.45)');
 if(walk){var st=Math.sin(t*12+k);E(c,x-2.4*s,y+5.6*s+(st>0?-.8*s:0),1.6*s,1*s,SH(col,-.35));E(c,x+2.4*s,y+5.6*s+(st<0?-.8*s:0),1.6*s,1*s,SH(col,-.35))}
 var by=y+bob;c.save();c.translate(x,by);c.scale(1/sq,sq);c.translate(-x,-by);
 var g=c.createRadialGradient(x-2*s,by-3*s,.5*s,x,by,7.5*s);g.addColorStop(0,SH(col,.35));g.addColorStop(.6,col);g.addColorStop(1,SH(col,-.28));
 c.beginPath();
 if(typ==='blob'){c.moveTo(x-6*s,by+3*s);c.bezierCurveTo(x-7.2*s,by-3*s,x-4*s,by-6.6*s,x,by-6.6*s);c.bezierCurveTo(x+4.6*s,by-6.6*s,x+7*s,by-3*s,x+6.2*s,by+2.6*s);c.bezierCurveTo(x+5.6*s,by+5.4*s,x-5.4*s,by+5.6*s,x-6*s,by+3*s)}
 else if(typ==='round'){c.arc(x,by-.6*s,6.2*s,0,6.2832)}
 else if(typ==='square'){RR(c,x-5.8*s,by-6*s,11.6*s,11.2*s,2.6*s)}
 else if(typ==='drop'){c.moveTo(x,by-8*s);c.bezierCurveTo(x+3*s,by-4*s,x+6.4*s,by-1*s,x+6*s,by+2*s);c.bezierCurveTo(x+5.4*s,by+6*s,x-5.4*s,by+6*s,x-6*s,by+2*s);c.bezierCurveTo(x-6.4*s,by-1*s,x-3*s,by-4*s,x,by-8*s)}
 else if(typ==='star'){for(var i=0;i<10;i++){var a=-Math.PI/2+i*Math.PI/5,rr=i%2?3.6*s:7.4*s,px=x+Math.cos(a)*rr,py=by+.6*s+Math.sin(a)*rr;i?c.lineTo(px,py):c.moveTo(px,py)}}
 else{c.moveTo(x-6*s,by+5*s);c.lineTo(x-6*s,by-1*s);c.arc(x,by-1*s,6*s,Math.PI,0);c.lineTo(x+6*s,by+5*s);for(i=0;i<4;i++){c.quadraticCurveTo(x+6*s-(i+.5)*3*s,by+(i%2?6.8:3.2)*s,x+6*s-(i+1)*3*s,by+5*s)}}
 c.closePath();c.fillStyle=g;c.fill();if(typ==='star'){c.lineJoin='round';c.strokeStyle=col;c.lineWidth=1.6*s;c.stroke()}
 c.restore();
 var arm=Math.sin(ph*1.3)*.8*s;if(typ!=='ghost'&&typ!=='round'){E(c,x-7.6*s,by+1.2*s+arm,1.5*s,1.5*s,SH(col,-.1));E(c,x+7.6*s,by+1.2*s-arm,1.5*s,1.5*s,SH(col,-.1))}
 else if(typ==='round'){E(c,x-7.2*s,by+1*s+arm,1.4*s,1.4*s,SH(col,-.15));E(c,x+7.2*s,by+1*s-arm,1.4*s,1.4*s,SH(col,-.15))}
 eyes(c,x,by-.6*s,s,bl,look);
 if(typ==='round'||typ==='ghost'){E(c,x-4.6*s,by+1.2*s,1.1*s,.6*s,'rgba(255,120,150,.35)');E(c,x+4.6*s,by+1.2*s,1.1*s,.6*s,'rgba(255,120,150,.35)')}
 return by}
function tag(c,txt,x,y,col){c.save();c.shadowColor='#000';c.shadowBlur=2;T(c,txt,x,y,5.2,col,'center','900');c.restore()}
function chief(c,x,y,t,th){var s=2.1,b=bot(c,'CHIEF',x,y,s,t,7,false),by=b-.6*s;
 c.beginPath();c.arc(x,by-1*s,7.4*s,Math.PI*1.08,Math.PI*1.92);c.strokeStyle='#2b2f34';c.lineWidth=1.5*s;c.stroke();c.beginPath();c.arc(x,by-1*s,7.4*s,Math.PI*1.12,Math.PI*1.5);c.strokeStyle='#444a51';c.lineWidth=.5*s;c.stroke();
 FR(c,x-8.6*s,by-3*s,3.2*s,6*s,1.4*s,'#22262b');FR(c,x+5.4*s,by-3*s,3.2*s,6*s,1.4*s,'#22262b');R(c,x-8.2*s,by-2.4*s,.8*s,4.6*s,'#3d434a');
 c.beginPath();c.moveTo(x-7.4*s,by+2*s);c.quadraticCurveTo(x-6.6*s,by+5.4*s,x-2.6*s,by+4.4*s);c.strokeStyle='#2b2f34';c.lineWidth=.7*s;c.stroke();E(c,x-2.4*s,by+4.4*s,.9*s,.9*s,A(th,1));
 return b}
function bubble(c,txt,x,y,a,col){c.save();c.globalAlpha=a;var fs=6.2;txt=txt.length>42?txt.slice(0,41)+'\u2026':txt;var w=TW(c,txt,fs,'700')+10,bx=Math.max(3,Math.min(W-w-3,x-w/2)),by=y-17;
 FR(c,bx,by,w,12.5,2,'#08090b',col||'#e9e9e9',1);P(c,[[Math.max(bx+4,Math.min(bx+w-8,x-3)),by+12.4],[Math.max(bx+7,Math.min(bx+w-5,x+3)),by+12.4],[Math.max(bx+4,Math.min(bx+w-8,x-1)),by+16]],'#08090b');
 c.beginPath();var ax=Math.max(bx+4,Math.min(bx+w-8,x-3));c.moveTo(ax,by+12.5);c.lineTo(ax+1.6,by+16);c.lineTo(ax+6,by+12.5);c.strokeStyle=col||'#e9e9e9';c.lineWidth=1;c.stroke();R(c,ax+.6,by+11.5,5,1.6,'#08090b');
 T(c,txt,bx+5,by+8.6,fs,'#f2f2f2','left','700');c.restore()}
/* ---------- dynamic layer ---------- */
var SPOTS=[[266,250],[394,330],[528,300],[140,336],[352,252],[528,214]];
function seatPos(k){var s=SL[k%6];return[s[0]+41,s[1]+74]}
function drawDyn(c,d,t,v){var th=d.theme,i;
 c.save();c.beginPath();c.rect(WM.x-4,3,WM.w+8,11);c.clip();var tape=(d.tape||'')+'   \u00b7   ';c.font='800 6.4px '+MONO;var tw=c.measureText(tape).width||300,off=(t*22)%tw;
 for(i=-1;i<3;i++)T(c,tape,WM.x-4-off+i*tw,11.2,6.4,th,'left','800');c.restore();L(c,WM.x-4,14.5,WM.x+WM.w+4,14.5,A(th,.55),.8);
 var cs=d.candles||[];if(cs.length>1){var lo=1e99,hi=-1e99;cs.forEach(function(b){lo=Math.min(lo,b[2]);hi=Math.max(hi,b[1])});var rg=(hi-lo)||Math.abs(hi)*.01||1;lo-=rg*.06;hi+=rg*.06;rg=hi-lo;
  var lb=cs[cs.length-1],bw=(WM.w-34)/cs.length,px=WM.x+4+(cs.length-.5)*bw,py=WM.y+28+78*(1-(lb[3]-lo)/rg);c.save();c.globalAlpha=.55+.45*Math.sin(t*4);c.shadowColor=lb[3]>=lb[0]?GRN:RED;c.shadowBlur=8;E(c,px,py,2.4,2.4,c.shadowColor);c.restore()}
 R(c,WM.x,WM.y+((t*30)%WM.h),WM.w,1.2,'rgba(255,255,255,.025)');
 for(i=0;i<6;i++){var s=SL[i];R(c,s[0]+12,s[1]+2+((t*10+i*7)%26),46,.8,A(th,.2));if(Math.sin(t*3+i)>.6)E(c,s[0]+56,s[1]+5.5,.9,.9,th)}
 var Z=new Date(),hm='',dl='';try{hm=Z.toLocaleTimeString('de-DE',{timeZone:'Europe/Berlin',hour:'2-digit',minute:'2-digit'});dl=Z.toLocaleDateString('en-GB',{timeZone:'Europe/Berlin',day:'2-digit',month:'short'}).toUpperCase()}catch(e){hm=('0'+Z.getHours()).slice(-2)+':'+('0'+Z.getMinutes()).slice(-2)}
 var tz='MEZ';try{var o=new Intl.DateTimeFormat('en-US',{timeZone:'Europe/Berlin',timeZoneName:'short'}).formatToParts(Z).filter(function(p){return p.type==='timeZoneName'})[0];tz=o&&/\+2|CEST/.test(o.value)?'CEST':'MEZ'}catch(e){}
 c.save();c.shadowColor=GRN;c.shadowBlur=6;T(c,hm,579,82,13,GRN,'center','800');c.restore();T(c,(dl||'')+' \u00b7 '+tz,579,89,3.8,A(GRN,.6),'center','800');
 for(i=0;i<9;i++)for(var j=0;j<4;j++){var on=Math.sin(t*(2+j*.7)+i*1.9+j*3.1)>.05,uy=198+30+i*((150-36)/9);R(c,652+7+j*3.2,uy+4,1.8,1.8,on?(j===3&&i%4===0?RED:th):'#13241a')}
 var ry=Math.sin(t*1.6)*1.4,rx=595,rb=236+ry;c.save();
 var fl=5+Math.sin(t*23)*1.6+Math.random()*1.5;c.beginPath();c.moveTo(rx-3,rb-6);c.quadraticCurveTo(rx,rb-6+fl*1.8,rx+3,rb-6);c.fillStyle='#ff9f1a';c.fill();c.beginPath();c.moveTo(rx-1.6,rb-6);c.quadraticCurveTo(rx,rb-6+fl,rx+1.6,rb-6);c.fillStyle='#fff3b0';c.fill();
 P(c,[[rx-6,rb-12],[rx-10,rb-5],[rx-4,rb-8]],'#8d969f');P(c,[[rx+6,rb-12],[rx+10,rb-5],[rx+4,rb-8]],'#8d969f');
 var gr=c.createLinearGradient(rx-5,0,rx+5,0);gr.addColorStop(0,'#c4cbd2');gr.addColorStop(.45,'#ffffff');gr.addColorStop(1,'#9aa3ac');
 c.beginPath();c.moveTo(rx,rb-46);c.bezierCurveTo(rx+6,rb-38,rx+6,rb-20,rx+5,rb-8);c.lineTo(rx-5,rb-8);c.bezierCurveTo(rx-6,rb-20,rx-6,rb-38,rx,rb-46);c.fillStyle=gr;c.fill();
 R(c,rx-5,rb-9,10,2,'#6c757e');E(c,rx,rb-28,3.6,3.6,'#1b2026');c.save();c.beginPath();c.arc(rx,rb-28,3,0,6.3);c.clip();logoK(c,d.logo,rx-3,rb-31,6,th);c.restore();L(c,rx,rb-12,rx,rb-8,'#6c757e',1.4);c.restore();
 T(c,d.top||'',595,252,4.8,d.top&&d.top.indexOf('-')>0?RED:th,'center','800',SANS);
 dishS(c,594,326,th);for(i=0;i<3;i++){var ar=((t*14+i*7)%21)+3;c.beginPath();c.arc(586,300,ar,-1.25,.05);c.strokeStyle=A(th,Math.max(0,.9-ar/24));c.lineWidth=1.3;c.stroke()}
 T(c,d.radar||'',595,346,3.8,'#9aa3ab','center','700');
 var bots=(d.bots||[]).slice(0,6),pos=[],n=bots.length,wk=n?Math.floor(t/22)%n:-1;
 bots.forEach(function(b,k){var cfg=BOT[b.n]||['#9ca3af','blob'],sp=seatPos(k),x=sp[0],y=sp[1]-10,walk=false;
  if(k===wk){var ph=t%22,dst=SPOTS[(Math.floor(t/22)+k)%SPOTS.length],f=0;
   if(ph>12&&ph<15)f=(ph-12)/3;else if(ph>=15&&ph<18)f=1;else if(ph>=18&&ph<21)f=1-(ph-18)/3;
   if(f>0){var e=f<.5?2*f*f:1-Math.pow(-2*f+2,2)/2;x=x+(dst[0]-x)*e;y=y+(dst[1]-10-y)*e;walk=(ph>12&&ph<15)||(ph>=18&&ph<21)}}
  var by=bot(c,b.n,x,y,1.5,t,k,walk);tag(c,b.n,x,by-12.5,cfg[0]);pos.push([x,by-17,b,cfg[0]])});
 var ch=bots.filter(function(b){return b.n==='CHIEF'})[0];var cy=chief(c,614,141,t,th);headDesk(c,th);tag(c,'CHIEF',614,cy-19,'#f2f2f2');pos.push([614,cy-23,ch||{n:'CHIEF',say:''},'#f2f2f2']);
 var AL=d.alert&&(Date.now()/1000-d.alert.t)<7?d.alert:null;if(AL){var ap=pos.filter(function(p){return p[2]&&p[2].n===AL.n})[0]||pos[0];if(ap){var ag=Date.now()/1000-AL.t;bubble(c,AL.txt,ap[0],ap[1]-4*Math.max(0,1-ag*3),ag<.25?ag/.25:ag>6.4?(7-ag)/.6:1,'#ffd34d');pos=pos.filter(function(p){return p!==ap})}}
 var speak=pos.filter(function(p){return p[2]&&p[2].say});if(speak.length){var q=t/3.6,k2=Math.floor(q)%speak.length,fr=q-Math.floor(q),al=fr<.1?fr/.1:fr>.9?(1-fr)/.1:1;
  bubble(c,speak[k2][2].say,speak[k2][0],speak[k2][1],al,k2%2?'#ff6fb5':'#e9e9e9');if(speak.length>3){var k3=(k2+2)%speak.length;bubble(c,speak[k3][2].say,speak[k3][0],speak[k3][1],al*.9,k3%2?'#ff6fb5':'#e9e9e9')}}
 v.fl=v.fl||[];if(!v.nf||t>v.nf){v.nf=t+2+Math.random()*1.4;var fls=d.floats&&d.floats.length?d.floats:(d.note!=='flat'?[d.pct]:[]);if(fls.length){var val=fls[(v.fc=(v.fc||0)+1)%fls.length];
  var an=pos.length?pos[Math.floor(Math.random()*Math.min(6,pos.length))]:[343,90];v.fl.push({x:an[0]+(Math.random()*16-8),y:an[1]-6,v:val,t0:t})}}
 v.fl=v.fl.filter(function(f){return t-f.t0<2.2});v.fl.forEach(function(f){var p=(t-f.t0)/2.2;c.save();c.globalAlpha=p<.15?p/.15:1-p;var col=f.v>=0?GRN:RED;c.shadowColor=col;c.shadowBlur=6;
  T(c,(f.v>=0?'+':'')+Number(f.v).toFixed(1)+'%',f.x,f.y-p*26,8.5,col,'center','900',SANS);c.restore()})}
/* ---------- loop ---------- */
var last=0,running=false;
function size(v){var dp=DPR(),cw=v.cv.clientWidth,chh=v.cv.clientHeight,w=Math.round(cw*dp),h=Math.round(chh*dp);if(!w||!h)return false;
 if(v.cv.width!==w||v.cv.height!==h||!v.st||v.dirty){v.cv.width=w;v.cv.height=h;v.k=w/W;v.ky=h/H;v.dp=dp;v.cw=cw;v.chh=chh;var st=v.st||document.createElement('canvas');st.width=w;st.height=h;var sc=st.getContext('2d');
  sc.setTransform(1,0,0,1,0,0);sc.clearRect(0,0,w,h);if(v.mon){sc.setTransform(dp,0,0,dp,0,0);try{drawBig(sc,cw,chh,v.d,v.mon,v)}catch(e){if(window.console)console.warn('floor big',e)}}
  else{sc.setTransform(v.k,0,0,v.ky,0,0);try{drawStatic(sc,v.d)}catch(e){if(window.console)console.warn('floor static',e)}}v.st=st;v.dirty=false}return true}
function vis(el){var r=el.getBoundingClientRect();return r.width>0&&r.bottom>0&&r.top<(window.innerHeight||800)}
var HOV=null;
function outline(c,r,a,lab){c.save();c.globalAlpha=a;c.shadowColor='#fff';c.shadowBlur=6;FR(c,r.x-1,r.y-1,r.w+2,r.h+2,3,null,'#ffffff',1);c.restore();
 if(lab){c.save();c.globalAlpha=a;var tw=TW(c,lab,5.2,'800',SANS)+8;FR(c,r.x+r.w/2-tw/2,r.y-9,tw,8,4,'#ffffff');T(c,lab,r.x+r.w/2,r.y-3,5.2,'#000','center','800',SANS);c.restore()}}
function paint(now,force){var t=now/1000;
 views.forEach(function(v){if(!v.d||!vis(v.cv)||!size(v))return;var c=v.cv.getContext('2d');c.setTransform(1,0,0,1,0,0);c.imageSmoothingEnabled=false;c.drawImage(v.st,0,0);c.imageSmoothingEnabled=true;
  if(v.mon){c.setTransform(v.dp,0,0,v.dp,0,0);try{dynBig(c,v.cw,v.chh,v.d,v,t)}catch(e){}return}
  c.setTransform(v.k,0,0,v.ky,0,0);
  try{drawDyn(c,v.d,t,v)}catch(e){if(!v.err){v.err=1;if(window.console)console.warn('floor dyn',e)}}
  if(v.single){var rs=monRects();if(v.hint0==null)v.hint0=t;var ha=1-(t-v.hint0)/1.8;if(ha>0)rs.forEach(function(r){outline(c,r,ha*.55,null)});
   if(HOV)rs.forEach(function(r){if(r.key===HOV)outline(c,r,1,r.key==='wall'?'TAP TO ENLARGE':'ENLARGE')})}})}
function frame(now){requestAnimationFrame(frame);if(document.hidden)return;var single=views.some(function(v){return v.single&&vis(v.cv)});if(now-last<(single?40:66))return;last=now;paint(now)}
function hitAt(x,y){var v=views.filter(function(q){return q.single&&!q.mon})[0];if(!v)return null;var r=v.cv.getBoundingClientRect();if(!r.width)return null;var lx=(x-r.left)/r.width*W,ly=(y-r.top)/r.height*H,best=null;
 monRects().forEach(function(m){var pad=m.key==='wall'?0:4;if(lx>=m.x-pad&&lx<=m.x+m.w+pad&&ly>=m.y-pad&&ly<=m.y+m.h+pad)best=m.key});return best}
window.DeskFloor={set:function(list){views.length=0;Array.prototype.push.apply(views,list);views.forEach(function(v){v.dirty=true});if(!running){running=true;requestAnimationFrame(frame)}},
 update:function(desks){views.forEach(function(v){if(desks[v.idx]){v.d=desks[v.idx];v.dirty=true}})},views:function(){return views},v:3,W:W,H:H,now:function(){paint(performance.now(),true)},hit:hitAt,hover:function(k){HOV=k||null},
 rect:function(k){return monRects().filter(function(m){return m.key===k})[0]||null},
 label:function(d,k){if(k==='wall')return'main screen';var o=monInfo(d,+k.charAt(1),k.charAt(2)==='b'?1:0);return o.lab+(o.k===0?' \u00b7 '+o.name:'')}};
})();
