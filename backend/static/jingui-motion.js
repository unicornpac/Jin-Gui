(() => {
  'use strict';

  const boot = () => {
    const root = document.documentElement;
    if (root.dataset.jgMotion === 'ready') return;
    root.dataset.jgMotion = 'ready';
    root.classList.add('jg-enhanced');

    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const finePointer = matchMedia('(pointer: fine)').matches;
    const body = document.body;

    const progress = document.createElement('div');
    progress.className = 'jg-scroll-progress';
    progress.setAttribute('aria-hidden', 'true');
    body.appendChild(progress);

    const syncScroll = () => {
      const max = Math.max(1, document.documentElement.scrollHeight - innerHeight);
      progress.style.transform = `scaleX(${Math.min(1, scrollY / max)})`;
    };
    addEventListener('scroll', syncScroll, { passive: true });
    syncScroll();

    const revealSelector = [
      '.hero', '.portal-actions .card', '.stats-section', '.browse-section',
      '.sidebar', '.chat-container', '.library-intro', '.tabs',
      '.library-group-title', '.disease-card', '.text-item',
      '.console-intro', '.stat-card', '.panel.active .card'
    ].join(',');

    let revealObserver;
    if (!reduced && 'IntersectionObserver' in window) {
      revealObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add('jg-in');
          revealObserver.unobserve(entry.target);
        });
      }, { threshold: 0.08, rootMargin: '0px 0px -5% 0px' });
    }

    const registerReveals = (scope = document) => {
      scope.querySelectorAll(revealSelector).forEach((element, index) => {
        if (element.dataset.jgReveal) return;
        element.dataset.jgReveal = '1';
        element.classList.add('jg-reveal');
        element.style.setProperty('--jg-delay', `${Math.min(index % 6, 5) * 55}ms`);
        if (revealObserver) revealObserver.observe(element);
        else element.classList.add('jg-in');
      });
    };
    registerReveals();

    const mutationObserver = new MutationObserver((records) => {
      records.forEach((record) => record.addedNodes.forEach((node) => {
        if (node.nodeType === 1) registerReveals(node);
      }));
    });
    mutationObserver.observe(body, { childList: true, subtree: true });

    if (reduced) return;

    let pointerX = innerWidth * 0.68;
    let pointerY = innerHeight * 0.28;
    let pointerLive = false;
    const syncPointer = (event) => {
      pointerX = event.clientX;
      pointerY = event.clientY;
      pointerLive = true;
      const nx = (pointerX / innerWidth - 0.5) * 2;
      const ny = (pointerY / innerHeight - 0.5) * 2;
      root.style.setProperty('--jg-x', nx.toFixed(3));
      root.style.setProperty('--jg-y', ny.toFixed(3));
      root.style.setProperty('--jg-px', `${pointerX}px`);
      root.style.setProperty('--jg-py', `${pointerY}px`);
    };
    addEventListener('pointermove', syncPointer, { passive: true });
    addEventListener('pointerleave', () => { pointerLive = false; }, { passive: true });

    if (finePointer) {
      const tiltSelector = '.portal-actions .card,.stats-section,.disease-card,.diff-btn';
      const magneticSelector = '.hero-btn,.card .btn,.btn-primary,.chat-input button,.ai-btn';
      let activeTilt = null;
      let activeMagnet = null;

      addEventListener('pointermove', (event) => {
        const target = event.target instanceof Element ? event.target : null;
        if (!target) return;

        const tilt = target.closest(tiltSelector);
        if (activeTilt && activeTilt !== tilt) {
          activeTilt.style.removeProperty('--jg-rx');
          activeTilt.style.removeProperty('--jg-ry');
        }
        activeTilt = tilt;
        if (tilt) {
          const rect = tilt.getBoundingClientRect();
          const rx = ((event.clientY - rect.top) / rect.height - 0.5) * -3.2;
          const ry = ((event.clientX - rect.left) / rect.width - 0.5) * 4.2;
          tilt.style.setProperty('--jg-rx', `${rx.toFixed(2)}deg`);
          tilt.style.setProperty('--jg-ry', `${ry.toFixed(2)}deg`);
        }

        const magnet = target.closest(magneticSelector);
        if (activeMagnet && activeMagnet !== magnet) {
          activeMagnet.style.removeProperty('--jg-bx');
          activeMagnet.style.removeProperty('--jg-by');
        }
        activeMagnet = magnet;
        if (magnet) {
          const rect = magnet.getBoundingClientRect();
          const bx = ((event.clientX - rect.left) / rect.width - 0.5) * 7;
          const by = ((event.clientY - rect.top) / rect.height - 0.5) * 5;
          magnet.style.setProperty('--jg-bx', `${bx.toFixed(2)}px`);
          magnet.style.setProperty('--jg-by', `${by.toFixed(2)}px`);
        }
      }, { passive: true });

      addEventListener('pointerout', (event) => {
        if (!(event.target instanceof Element)) return;
        const tilt = event.target.closest(tiltSelector);
        if (tilt && !tilt.contains(event.relatedTarget)) {
          tilt.style.removeProperty('--jg-rx');
          tilt.style.removeProperty('--jg-ry');
        }
        const magnet = event.target.closest(magneticSelector);
        if (magnet && !magnet.contains(event.relatedTarget)) {
          magnet.style.removeProperty('--jg-bx');
          magnet.style.removeProperty('--jg-by');
        }
      }, { passive: true });
    }

    const canvas = document.createElement('canvas');
    canvas.id = 'jg-atmosphere';
    canvas.setAttribute('aria-hidden', 'true');
    body.appendChild(canvas);
    const context = canvas.getContext('2d', { alpha: true });
    if (!context) return;

    let width = 0;
    let height = 0;
    let ratio = 1;
    let particles = [];
    const makeParticle = () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.16,
      vy: (Math.random() - 0.5) * 0.12,
      radius: 0.45 + Math.random() * 1.25,
      alpha: 0.08 + Math.random() * 0.18
    });

    const resize = () => {
      ratio = Math.min(devicePixelRatio || 1, 1.75);
      width = innerWidth;
      height = innerHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      const count = width < 720 ? 18 : Math.min(42, Math.round(width / 34));
      particles = Array.from({ length: count }, makeParticle);
    };
    addEventListener('resize', resize, { passive: true });
    resize();

    let frame = 0;
    let running = true;
    const draw = () => {
      if (!running) return;
      context.clearRect(0, 0, width, height);

      if (pointerLive) {
        const glow = context.createRadialGradient(pointerX, pointerY, 0, pointerX, pointerY, 190);
        glow.addColorStop(0, 'rgba(209,177,109,.055)');
        glow.addColorStop(1, 'rgba(209,177,109,0)');
        context.fillStyle = glow;
        context.fillRect(pointerX - 190, pointerY - 190, 380, 380);
      }

      particles.forEach((particle) => {
        if (pointerLive) {
          const dx = particle.x - pointerX;
          const dy = particle.y - pointerY;
          const distance = Math.hypot(dx, dy);
          if (distance < 115 && distance > 0) {
            const force = (1 - distance / 115) * 0.022;
            particle.vx += dx / distance * force;
            particle.vy += dy / distance * force;
          }
        }
        particle.vx *= 0.992;
        particle.vy *= 0.992;
        particle.x += particle.vx;
        particle.y += particle.vy;
        if (particle.x < -8) particle.x = width + 8;
        if (particle.x > width + 8) particle.x = -8;
        if (particle.y < -8) particle.y = height + 8;
        if (particle.y > height + 8) particle.y = -8;
        context.beginPath();
        context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
        context.fillStyle = `rgba(209,177,109,${particle.alpha})`;
        context.fill();
      });

      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);

    document.addEventListener('visibilitychange', () => {
      running = !document.hidden;
      if (running) frame = requestAnimationFrame(draw);
      else cancelAnimationFrame(frame);
    });
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
