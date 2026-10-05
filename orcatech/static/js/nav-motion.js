/* OrçaTech · nav-motion.js
   Porta para JS puro das ideias do Motion/React: layoutId (indicador que viaja
   entre itens, inclusive entre páginas), spring física, entrada escalonada. */
(() => {
  'use strict';
  const doc = document, root = doc.documentElement;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const norm = s => (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, ' ').trim();
  const store = {
    get() { try { return JSON.parse(sessionStorage.getItem('nm:ind')); } catch (e) { return null; } },
    set(v) { try { sessionStorage.setItem('nm:ind', JSON.stringify(v)); } catch (e) {} }
  };

  /* ── Spring real → curva linear() do CSS ───────────────── */
  const canLinear = (() => { try { return CSS.supports('animation-timing-function', 'linear(0,1)'); } catch (e) { return false; } })();
  function spring(k, c, m = 1) {
    const w0 = Math.sqrt(k / m), z = c / (2 * Math.sqrt(k * m)), wd = w0 * Math.sqrt(1 - z * z);
    const f = t => 1 - Math.exp(-z * w0 * t) * (Math.cos(wd * t) + (z * w0 / wd) * Math.sin(wd * t));
    let dur = 0;
    for (let t = 0; t < 5; t += 0.01) if (Math.abs(1 - f(t)) > 0.002) dur = t;
    dur += 0.02;
    const n = Math.ceil(dur * 60), pts = [];
    for (let i = 0; i <= n; i++) pts.push(f(i / n * dur).toFixed(4));
    pts[n] = '1';
    return canLinear
      ? { easing: `linear(${pts.join(',')})`, duration: Math.round(dur * 1000) }
      : { easing: 'cubic-bezier(.34,1.4,.64,1)', duration: 650 };
  }
  const MOVE = spring(300, 22), REVEAL = spring(170, 19);
  if (canLinear) {
    root.style.setProperty('--nm-spring', REVEAL.easing);
    root.style.setProperty('--nm-spring-dur', REVEAL.duration + 'ms');
  }

  /* ── Identidade de cada página (cor + assinatura) ──────── */
  const PAGES = [
    ['aprovac', 150, 'aprovacoes'], ['alerta', 38, 'alerta'], ['usuario', 196, 'usuarios'],
    ['estrutura', 318, 'estrutura'], ['departamento', 318, 'estrutura'],
    ['relatorios empresariais', 338, 'rel-emp'], ['relatorios da empresa', 338, 'rel-emp'],
    ['relatorio', 172, 'relatorios'], ['orcamento', 238, 'orcamentos'],
    ['fornecedor', 276, 'fornecedores'], ['carrinho', 24, 'carrinho'], ['dashboard', 214, 'dashboard']
  ];
  const pageOf = a => { const t = norm(a && a.textContent); return PAGES.find(p => t.includes(p[0])) || null; };
  const setPage = p => { if (!p) return; root.style.setProperty('--nm-h', p[1]); root.dataset.nmPage = p[2]; };

  /* ── Sidebar: item atual + indicador líquido ───────────── */
  const nav = doc.querySelector('.sidebar-nav, .side-nav');
  let cur = null, ind = null, core = null;

  function pickCurrent(links) {
    const path = location.pathname.replace(/\/+$/, '') || '/';
    const score = a => {
      const u = new URL(a.href, location.href);
      if (u.origin !== location.origin) return -1;
      const p = u.pathname.replace(/\/+$/, '') || '/';
      if (p === '/') return path === '/' ? 1 : -1;
      return (path === p || path.startsWith(p + '/')) ? p.length : -1;
    };
    const best = links.map(a => [a, score(a)]).filter(x => x[1] > 0).sort((a, b) => b[1] - a[1])[0];
    return (best && best[0]) || links.find(a => a.classList.contains('ativo') || a.classList.contains('on')) || null;
  }
  const box = a => ({ t: a.offsetTop, h: a.offsetHeight, l: a.offsetLeft, w: a.offsetWidth, s: nav.scrollTop });
  const place = b => {
    ind.style.width = b.w + 'px'; ind.style.height = b.h + 'px';
    ind.style.transform = `translate3d(${b.l}px,${b.t}px,0)`;
  };
  const curBox = () => {
    const cs = getComputedStyle(ind), m = new DOMMatrix(cs.transform);
    return { l: m.m41, t: m.m42, h: parseFloat(cs.height) || 0, w: parseFloat(cs.width) || 0 };
  };
  function glide(to, from) {
    from = from || curBox();
    ind.getAnimations().forEach(a => a.cancel());
    place(to);
    const tf = b => `translate3d(${b.l}px,${b.t}px,0)`;
    ind.animate(
      [{ transform: tf(from), height: from.h + 'px', width: from.w + 'px' },
       { transform: tf(to), height: to.h + 'px', width: to.w + 'px' }],
      { duration: MOVE.duration, easing: MOVE.easing });
    const s = Math.min(Math.abs(to.t - from.t) / 240, 0.6);   // esticar como líquido
    if (s > 0.02) core.animate(
      [{ transform: 'scale(1,1)' }, { transform: `scale(${1 - s * 0.06},${1 + s})`, offset: 0.28 }, { transform: 'scale(1,1)' }],
      { duration: MOVE.duration * 0.75, easing: 'ease-out' });
  }
  function ripple(a, e) {
    const r = a.getBoundingClientRect(), s = doc.createElement('span');
    s.className = 'nm-rip';
    s.style.left = (e.detail ? e.clientX - r.left : r.width / 2) + 'px';
    s.style.top = (e.detail ? e.clientY - r.top : r.height / 2) + 'px';
    a.appendChild(s); setTimeout(() => s.remove(), 700);
  }

  if (nav) {
    const links = [...nav.querySelectorAll('a[href]')];
    cur = pickCurrent(links);
    if (cur) {
      links.forEach(a => a.classList.remove('ativo', 'on'));
      cur.classList.add('nm-on');
      cur.setAttribute('aria-current', 'page');
      cur.querySelectorAll('.icon svg :is(path,circle,rect,line,polyline,polygon)').forEach(p => p.setAttribute('pathLength', '1'));
      setPage(pageOf(cur));

      ind = doc.createElement('div'); ind.className = 'nm-ind'; ind.setAttribute('aria-hidden', 'true');
      core = doc.createElement('i'); core.className = 'nm-core'; ind.appendChild(core);
      nav.prepend(ind);

      const saved = store.get();
      if (saved && typeof saved.s === 'number') nav.scrollTop = saved.s;
      const target = box(cur);
      ind.classList.add('nm-show');
      if (saved && !reduce && (saved.t !== target.t || saved.h !== target.h)) {
        place(saved); void ind.offsetWidth;
        requestAnimationFrame(() => glide(target, saved));
      } else {
        place(target);
        if (!reduce) core.animate([{ opacity: 0, transform: 'scale(.85)' }, { opacity: 1, transform: 'scale(1)' }],
          { duration: REVEAL.duration, easing: REVEAL.easing });
      }
      store.set(target);

      addEventListener('resize', () => { if (!ind.getAnimations().length) { const b = box(cur); place(b); store.set(b); } });
    }

    nav.addEventListener('pointermove', e => {
      if (e.pointerType !== 'mouse') return;
      const a = e.target.closest('a'); if (!a) return;
      const r = a.getBoundingClientRect();
      a.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      a.style.setProperty('--my', (e.clientY - r.top) + 'px');
    });

    nav.addEventListener('click', e => {
      const a = e.target.closest('a[href]');
      if (!a || !nav.contains(a) || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || a.target === '_blank') return;
      const u = new URL(a.href, location.href);
      if (u.origin !== location.origin || (u.pathname === location.pathname && u.hash)) return;
      ripple(a, e);
      if (reduce || !ind || a === cur) return;
      e.preventDefault();
      const b = box(a);
      glide(b); store.set(b);
      cur.classList.remove('nm-on'); a.classList.add('nm-on'); cur = a;
      setPage(pageOf(a));
      setTimeout(() => { location.href = a.href; }, 230);   // deixa a mola andar antes de navegar
    });
  }

  /* ── Conteúdo: entrada escalonada, count-up, tilt ──────── */
  const NUM = /^(R\$\s*)?(-?\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?(\s*%)?$/;
  function countUp(el, delay) {
    const raw = el.textContent.trim(), m = raw.match(NUM);
    if (!m || raw.length > 14 || /^(19|20)\d\d$/.test(raw)) return;
    const dec = m[3] ? m[3].length : 0, to = parseFloat(m[2].replace(/\./g, '') + (m[3] ? '.' + m[3] : ''));
    if (!isFinite(to) || to === 0) return;
    const fmt = v => (m[1] || '') + v.toLocaleString('pt-BR', { minimumFractionDigits: dec, maximumFractionDigits: dec }) + (m[4] || '');
    el.style.fontVariantNumeric = 'tabular-nums';
    el.textContent = fmt(0);
    setTimeout(() => {
      const t0 = performance.now(), D = 1100;
      (function step(now) {
        const p = Math.min((now - t0) / D, 1);
        el.textContent = p < 1 ? fmt(to * (1 - Math.pow(1 - p, 4))) : raw;
        if (p < 1) requestAnimationFrame(step);
      })(t0);
    }, delay);
  }

  const RES = !!doc.querySelector('.stats .stat-card, .melhor');
  const WAIT = !!doc.querySelector('.lojas .loja-item');
  if (!cur) {   // páginas sem menu lateral ganham cor própria
    if (WAIT) setPage(['', 190, 'aguardando']);
    else if (RES) setPage(['', 152, 'resultados']);
  }

  /* Telas sem menu lateral (aguardando/resultados) já têm animações próprias:
     aqui o nav-motion só COMPLEMENTA (cor da página, radar, brilho, count-up) e não substitui nada. */
  const COMP = !cur && (WAIT || RES);

  function aguardando() {
    const host = doc.querySelector('.page') || doc.body;
    host.classList.add('nm-clip');
    const t = doc.querySelector('.titulo');
    if (t) { const r = doc.createElement('div'); r.className = 'nm-radar'; r.setAttribute('aria-hidden', 'true'); r.innerHTML = '<i></i><i></i><i></i>'; t.prepend(r); }
    if (COMP) return;   // mantém fadeUp original de .titulo/.progress-wrap/.lojas/.loja-item
    const lojas = doc.querySelector('.lojas');
    if (lojas) lojas.style.animation = 'none';
    [...doc.querySelectorAll('.titulo,.progress-wrap,.dica,.timer')].forEach((el, i) => { el.style.setProperty('--i', i); el.classList.add('nm-rv'); });
    doc.querySelectorAll('.loja-item').forEach((el, k) => { el.style.setProperty('--k', Math.min(k, 12)); el.classList.add('nm-iv'); });
  }

  function reveal() {
    if (WAIT && !reduce) aguardando();
    const host = doc.querySelector('.main, main, .page, .wrap, .conteudo');
    if (!host || reduce) return;
    const Q = '.card,.tw,.kpi,.stat,.stat-card,.metric,.panel,.pager,.alert,.page-head,.ph,.page-header,.search-card,.lojas-card,.titulo-card,.melhor,.stat-card,.grid>*,.kpis>*,.stats>*,.cards>*';
    let els = [...host.querySelectorAll(Q)];
    els = els.filter(el => !els.some(o => o !== el && o.contains(el))).slice(0, 40);
    els.forEach((el, i) => {
      if (!COMP) { el.style.setProperty('--i', Math.min(i, 14)); el.classList.add('nm-rv'); }
      const delay = 330 + Math.min(i, 14) * 60;
      if (!el.matches('.tw,.pager,.alert,.ph,.page-head') && !(RES && el.matches('.card'))) {
        [...el.querySelectorAll('*')]
          .filter(n => !n.children.length && !n.closest('table,.pager,form,a,button,label,svg'))
          .slice(0, 12).forEach(n => countUp(n, delay));
      }
      if (!COMP && /card|kpi|stat|metric|panel/.test(String(el.className)) && !el.querySelector('table,form,input,select,textarea')) {
        el.setAttribute('data-nm-tilt', '');
        el.addEventListener('pointermove', e => {
          if (e.pointerType !== 'mouse') return;
          const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
          el.style.setProperty('--gx', x * 100 + '%'); el.style.setProperty('--gy', y * 100 + '%');
          el.style.setProperty('--rx', ((0.5 - y) * 5).toFixed(2) + 'deg');
          el.style.setProperty('--ry', ((x - 0.5) * 6).toFixed(2) + 'deg');
        });
      }
    });
    if (COMP) return;   // sem chips/linhas/tilt novos: já existem animações e hovers próprios
    host.querySelectorAll('.loja-chip,.chip-suggestion').forEach((el, k) => { el.style.setProperty('--k', Math.min(k, 14)); el.classList.add('nm-chip'); });
    host.querySelectorAll('tbody tr').forEach((tr, j) => {
      if (j < 14) { tr.style.setProperty('--j', j); tr.classList.add('nm-row'); }
    });
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', reveal);
  else reveal();
})();
