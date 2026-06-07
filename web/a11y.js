/*
  Shadow Ebook - 无障碍增强
  - ESC 键关闭最近的可见 modal
  - 设置 role="dialog" + aria-modal="true" + aria-label
  - 焦点陷阱 (Tab 循环在 modal 内)
*/
(function(){
  const MODAL_IDS = [
    'word-modal', 'ar-modal', 'review-modal', 'comp-modal',
    'grammar-modal', 'practice-modal'
  ];

  function getVisibleModal(){
    for(const id of MODAL_IDS){
      const el = document.getElementById(id);
      if(el && (el.classList.contains('show') || el.style.display !== 'none' && el.offsetParent !== null)){
        return el;
      }
    }
    return null;
  }

  // 找 modal 内第一个可聚焦元素
  function getFocusable(modal){
    return Array.from(modal.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )).filter(el => !el.disabled && el.offsetParent !== null);
  }

  document.addEventListener('keydown', (e) => {
    if(e.key !== 'Escape') return;
    const modal = getVisibleModal();
    if(!modal) return;
    e.preventDefault();
    // 调 modal 自己的 close 函数 (定义在各页里, 通过查找 onclick 或全局 close*)
    const closeBtn = modal.querySelector('[class*="close"]');
    if(closeBtn) closeBtn.click();
  });

  // 在 modal 打开时, 自动加 ARIA 属性 + 焦点管理
  function setupModal(id){
    const el = document.getElementById(id);
    if(!el) return;
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-label', id.replace(/-/g, ' '));

    // 焦点陷阱: Tab 循环
    el.addEventListener('keydown', (e) => {
      if(e.key !== 'Tab') return;
      const focusable = getFocusable(el);
      if(focusable.length === 0) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if(e.shiftKey && document.activeElement === first){
        e.preventDefault(); last.focus();
      } else if(!e.shiftKey && document.activeElement === last){
        e.preventDefault(); first.focus();
      }
    });
  }

  // DOMContentLoaded 时设置所有 modal
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', () => MODAL_IDS.forEach(setupModal));
  } else {
    MODAL_IDS.forEach(setupModal);
  }
})();
