/* Decorative motion only. No account actions and no continuously running JS loop. */
(() => {
  const root = document.documentElement;
  const toggle = document.getElementById("motionToggle");
  const light = document.getElementById("cursorLight");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const finePointer = matchMedia("(pointer: fine)");
  let enabled = true, frame = 0;
  try { enabled = localStorage.getItem("xhh-background-motion") !== "off"; } catch (_) { /* Optional preference. */ }
  function update() {
    const running = enabled && !reduced.matches && !document.hidden;
    root.dataset.motion = running ? "on" : "off";
    toggle.setAttribute("aria-pressed", String(enabled && !reduced.matches));
    toggle.textContent = reduced.matches ? "动效已随系统关闭" : "背景动效 · " + (enabled ? "开" : "关");
    toggle.disabled = reduced.matches;
    if (!running) { cancelAnimationFrame(frame); frame = 0; light.style.opacity = "0"; }
  }
  toggle.addEventListener("click", () => {
    enabled = !enabled;
    try { localStorage.setItem("xhh-background-motion", enabled ? "on" : "off"); } catch (_) { /* Keep session setting. */ }
    update();
  });
  document.addEventListener("pointermove", event => {
    if (root.dataset.motion !== "on" || !finePointer.matches || frame) return;
    const {clientX, clientY} = event;
    frame = requestAnimationFrame(() => {
      light.style.transform = `translate3d(${clientX - 250}px, ${clientY - 250}px, 0)`;
      light.style.opacity = "1";
      frame = 0;
    });
  }, {passive: true});
  document.documentElement.addEventListener("pointerleave", () => { light.style.opacity = "0"; });
  reduced.addEventListener("change", update);
  document.addEventListener("visibilitychange", update);
  update();

  // Keep navigation anchored to the existing sections, with a visible location.
  const links = [...document.querySelectorAll(".nav a")];
  const observed = new Map();
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) observed.set(entry.target.id, entry.isIntersecting);
    const active = links.find(link => observed.get(link.hash.slice(1)));
    for (const link of links) {
      if (link === active) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    }
  }, {rootMargin: "-70px 0px -45% 0px"});
  links.forEach(link => { const section = document.querySelector(link.hash); if (section) observer.observe(section); });
})();
