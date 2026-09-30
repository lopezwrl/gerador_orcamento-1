/* OrçaTech · animacoes.js — módulos independentes, todos opcionais */
(function(){
  'use strict';
  var reduzir = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $$ = function(s,c){return Array.prototype.slice.call((c||document).querySelectorAll(s));};

  /* 1. Spotlight: posiciona o brilho sob o cursor */
  function spotlight(){
    var raf=0,ev=null;
    document.addEventListener('mousemove',function(e){
      var c=e.target.closest&&e.target.closest('.card,.stat-card'); if(!c) return;
      ev=e; if(raf) return;
      raf=requestAnimationFrame(function(){
        raf=0; var r=c.getBoundingClientRect();
        c.style.setProperty('--mx',(ev.clientX-r.left)+'px');
        c.style.setProperty('--my',(ev.clientY-r.top)+'px');
      });
    },{passive:true});
  }

  /* 2. Linhas de tabela em cascata (máx. 12 para não demorar) */
  function linhas(){
    $$('tbody').forEach(function(tb){
      $$('tr',tb).forEach(function(tr,i){ if(tr.children.length<2) return;
        tr.classList.add('anim-row'); tr.style.setProperty('--i',Math.min(i,12)); });
    });
  }

  /* 3. Ripple */
  function ripple(){
    document.addEventListener('click',function(e){
      var b=e.target.closest&&e.target.closest('.btn,.btn-submit,.btn-sair'); if(!b) return;
      var r=b.getBoundingClientRect(), d=Math.max(r.width,r.height)*2, s=document.createElement('span');
      s.className='ripple'; s.style.width=s.style.height=d+'px';
      s.style.left=(e.clientX-r.left-d/2)+'px'; s.style.top=(e.clientY-r.top-d/2)+'px';
      b.appendChild(s); setTimeout(function(){s.remove();},650);
    });
  }

  /* 4. Revelar ao rolar (só cards que começam fora da tela) */
  function revelar(){
    if(!('IntersectionObserver' in window)) return;
    var io=new IntersectionObserver(function(es){
      es.forEach(function(x){ if(x.isIntersecting){ x.target.classList.add('rv-in'); io.unobserve(x.target);} });
    },{threshold:.12});
    $$('.card').forEach(function(c){
      if(c.getBoundingClientRect().top>window.innerHeight){ c.classList.add('rv'); io.observe(c); }
    });
  }

  /* 5. Barra de progresso na navegação */
  function progresso(){
    var bar=document.createElement('div'); bar.id='nav-progress'; document.body.appendChild(bar); var t;
    function ir(){ clearTimeout(t); bar.className=''; void bar.offsetWidth; bar.className='run'; t=setTimeout(fim,6000); }
    function fim(){ bar.className='done'; }
    document.addEventListener('click',function(e){
      var a=e.target.closest&&e.target.closest('a[href]'); if(!a||e.defaultPrevented) return;
      if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button) return;
      if(a.target==='_blank'||a.hasAttribute('download')) return;
      var u; try{u=new URL(a.href,location.href);}catch(_){return;}
      if(u.origin!==location.origin||(u.pathname===location.pathname&&u.search===location.search)) return;
      if(/pdf|exportar|csv|download/i.test(u.pathname)) return;
      ir();
    });
    document.addEventListener('submit',function(e){ if(!e.defaultPrevented) ir(); });
    window.addEventListener('pageshow',function(){ clearTimeout(t); bar.className=''; });
  }

  /* 6/7. Botão de tema gira ao alternar */
  function tema(){
    var b=document.getElementById('themeToggle'); if(!b) return;
    b.addEventListener('click',function(){ b.classList.remove('spin'); void b.offsetWidth; b.classList.add('spin');
      setTimeout(function(){b.classList.remove('spin');},600); });
  }

  /* 8. Contagem de valores em R$ (termina sempre no texto original) */
  function numeros(){
    if(reduzir||!('IntersectionObserver' in window)) return;
    var RE=/^([\s\S]*?R\$\s*-?)([\d.]+,\d{2})([\s\S]*)$/;
    function fmt(n){return n.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});}
    function animar(el,m,orig){
      var alvo=parseFloat(m[2].replace(/\./g,'').replace(',','.')), ini=null, dur=900;
      function passo(ts){ if(ini===null) ini=ts; var p=Math.min((ts-ini)/dur,1), e=1-Math.pow(1-p,3);
        el.textContent=(p<1)?m[1]+fmt(alvo*e)+m[3]:orig; if(p<1) requestAnimationFrame(passo); }
      requestAnimationFrame(passo);
    }
    var io=new IntersectionObserver(function(es){
      es.forEach(function(x){ if(!x.isIntersecting) return; io.unobserve(x.target);
        var orig=x.target.textContent, m=orig.trim().match(RE); if(m) animar(x.target,m,orig.trim()); });
    },{threshold:.4});
    $$('.total,.dado strong,td.dir,.stat-val').forEach(function(el){
      if(el.children.length===0 && RE.test(el.textContent.trim())) io.observe(el);
    });
  }

  function init(){
    spotlight(); ripple(); progresso(); tema();
    if(!reduzir){ linhas(); revelar(); numeros(); }
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init); else init();
})();