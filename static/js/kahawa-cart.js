/**
 * Kahawa client cart — localStorage, customize modal, and cart page helpers.
 * Cart shape: { [variantKey]: CartItem }
 * Pricing mirrors kahawa/pricing.py
 */
(function (window, document) {
  'use strict';

  const STORAGE_KEY = 'kahawa_cart';
  const RECENT_ORDERS_KEY = 'recent_orders';
  const LEGACY_RECENT_ORDERS_KEY = 'kahawa_recent_orders';

  const SIZE_EXTRAS = { Regular: 0, Large: 50 };
  const MILK_EXTRAS = { Dairy: 0, Oat: 50, Almond: 50 };
  const EXTRA_SHOT_FEE = 100;
  const DELIVERY_FEE = 100;
  const TAX_RATES = { A: 0, B: 16, C: 0, D: 0, E: 8 };

  function money(n) {
    return Math.round(Number(n) || 0).toLocaleString('en-KE');
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function customizationLabel(c) {
    if (!c) return '';
    if (c.components_label) return c.components_label;
    const bits = [];
    if (c.size) bits.push(c.size);
    if (c.milk) bits.push(`${c.milk} milk`);
    if (c.extra_shot) bits.push('Extra shot');
    return bits.join(' · ');
  }

  function selectedOrderType() {
    const el = document.querySelector('input[name="order_type"]:checked');
    return el ? el.value : 'PICKUP';
  }

  const KahawaCart = {
    DELIVERY_FEE,

    get() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : {};
      } catch (_) {
        return {};
      }
    },

    save(cart) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(cart));
      this.updateBadge();
      this.renderCartPage();
      window.dispatchEvent(new CustomEvent('kahawa:cart-updated', { detail: cart }));
    },

    clear() {
      localStorage.removeItem(STORAGE_KEY);
      this.updateBadge();
      this.renderCartPage();
      window.dispatchEvent(new CustomEvent('kahawa:cart-updated', { detail: {} }));
    },

    count() {
      return Object.values(this.get()).reduce((sum, item) => sum + (item.quantity || 0), 0);
    },

    subtotal() {
      return Object.values(this.get()).reduce(
        (sum, item) => sum + Number(item.unitPrice || 0) * Number(item.quantity || 0),
        0,
      );
    },

    totals(orderType, discount) {
      const items = Object.values(this.get());
      const subtotal = this.subtotal();
      const delivery = orderType === 'DELIVERY' ? DELIVERY_FEE : 0;
      let disc = Math.max(0, Math.round(Number(discount) || 0));
      const gross = subtotal + delivery;
      if (disc > gross) disc = gross;
      const parts = items.map((item) => ({
        amount: Number(item.unitPrice || 0) * Number(item.quantity || 0),
        code: item.taxType || 'B',
      }));
      if (delivery) parts.push({ amount: delivery, code: 'B' });
      const base = parts.reduce((sum, part) => sum + part.amount, 0);
      let remaining = disc;
      let tax = 0;
      parts.forEach((part, index) => {
        let share = 0;
        if (disc && base) {
          share = index === parts.length - 1
            ? remaining
            : Math.round((disc * part.amount) / base);
          if (index !== parts.length - 1) remaining -= share;
        }
        const net = Math.max(0, part.amount - share);
        const rate = TAX_RATES[part.code] ?? 16;
        if (rate) tax += (net * rate) / (100 + rate);
      });
      return {
        subtotal,
        tax: Math.round(tax),
        delivery,
        discount: disc,
        total: gross - disc,
      };
    },

    updateBadge() {
      const badge = document.getElementById('cart-count-badge');
      if (!badge) return;
      const count = this.count();
      badge.textContent = String(count);
      if (count > 0) {
        badge.classList.remove('hidden');
        badge.classList.add('flex');
      } else {
        badge.classList.add('hidden');
        badge.classList.remove('flex');
      }
    },

    variantKey(productId, customization) {
      const c = customization || {};
      const bits = [String(productId)];
      if (c.size) bits.push(`s:${c.size}`);
      if (c.milk) bits.push(`m:${c.milk}`);
      if (c.extra_shot) bits.push('shot');
      return bits.join('|');
    },

    addItem(item) {
      const cart = this.get();
      const key = item.packageId
        ? `pkg:${item.packageId}`
        : this.variantKey(item.productId, item.customization);
      if (cart[key]) {
        cart[key].quantity += item.quantity || 1;
      } else {
        cart[key] = {
          productId: item.productId || null,
          packageId: item.packageId || null,
          taxType: item.taxType || 'B',
          name: item.name,
          image: item.image || '',
          quantity: item.quantity || 1,
          unitPrice: item.unitPrice,
          customization: item.customization || {},
        };
      }
      this.save(cart);
      return key;
    },

    setQuantity(key, quantity) {
      const cart = this.get();
      if (!cart[key]) return;
      const qty = Math.max(0, parseInt(quantity, 10) || 0);
      if (qty <= 0) {
        delete cart[key];
      } else {
        cart[key].quantity = qty;
      }
      this.save(cart);
    },

    removeItem(key) {
      const cart = this.get();
      delete cart[key];
      this.save(cart);
    },

    getRecentOrders() {
      try {
        const primary = localStorage.getItem(RECENT_ORDERS_KEY);
        const legacy = localStorage.getItem(LEGACY_RECENT_ORDERS_KEY);
        const fromPrimary = primary ? JSON.parse(primary) : [];
        const fromLegacy = legacy ? JSON.parse(legacy) : [];
        const merged = [
          ...(Array.isArray(fromPrimary) ? fromPrimary : []),
          ...(Array.isArray(fromLegacy) ? fromLegacy : []),
        ];
        return [...new Set(merged.filter(Boolean))];
      } catch (_) {
        return [];
      }
    },

    addRecentOrder(orderCode) {
      if (!orderCode) return;
      const list = this.getRecentOrders().filter((c) => c !== orderCode);
      list.unshift(orderCode);
      const trimmed = list.slice(0, 20);
      localStorage.setItem(RECENT_ORDERS_KEY, JSON.stringify(trimmed));
      localStorage.setItem(LEGACY_RECENT_ORDERS_KEY, JSON.stringify(trimmed));
    },

    renderCartPage() {
      const itemsEl = document.getElementById('cart-page-items');
      const pageEl = document.getElementById('cart-page');
      const payBtn = document.getElementById('cart-pay-btn');
      if (!itemsEl) return;

      const cart = this.get();
      const entries = Object.entries(cart);
      pageEl?.classList.toggle('is-empty', !entries.length);

      if (!entries.length) {
        itemsEl.innerHTML = '';
        if (payBtn) payBtn.disabled = true;
      } else {

        itemsEl.innerHTML = entries
          .map(([key, item]) => {
            const line = Number(item.unitPrice) * Number(item.quantity);
            const custom = customizationLabel(item.customization);
            const img = item.image
              ? `<img src="${escapeHtml(item.image)}" alt="" class="h-full w-full object-cover">`
              : `<div class="flex h-full items-center justify-center text-espresso-800/30"><i data-lucide="coffee" class="h-5 w-5"></i></div>`;
            return `
              <article class="flex gap-3 rounded-2xl bg-cream-50 p-3 ring-1 ring-caramel-400/15 sm:p-4" data-cart-key="${escapeHtml(key)}">
                <div class="h-16 w-16 shrink-0 overflow-hidden rounded-xl bg-latte/50 sm:h-20 sm:w-20">${img}</div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0">
                      <h3 class="truncate text-sm font-extrabold text-espresso-900 sm:text-base">${escapeHtml(item.name)}</h3>
                      <p class="mt-0.5 text-xs font-semibold leading-snug text-espresso-700/55">${escapeHtml(custom)}</p>
                    </div>
                    <button type="button" class="js-cart-remove shrink-0 p-1 text-espresso-700/40 transition hover:text-red-600" data-key="${escapeHtml(key)}" aria-label="Remove">
                      <i data-lucide="trash-2" class="h-4 w-4"></i>
                    </button>
                  </div>
                  <div class="mt-2 flex items-center justify-between">
                    <div class="inline-flex items-center rounded-full bg-cream-100 ring-1 ring-caramel-400/20">
                      <button type="button" class="js-cart-qty h-8 w-8 font-extrabold text-espresso-800" data-key="${escapeHtml(key)}" data-delta="-1" aria-label="Decrease">−</button>
                      <span class="min-w-[1.5rem] text-center text-sm font-extrabold">${item.quantity}</span>
                      <button type="button" class="js-cart-qty h-8 w-8 font-extrabold text-espresso-800" data-key="${escapeHtml(key)}" data-delta="1" aria-label="Increase">+</button>
                    </div>
                    <p class="text-sm font-extrabold text-espresso-900">KSh ${money(line)}</p>
                  </div>
                </div>
              </article>
            `;
          })
          .join('');
      }

      const discountEl = document.getElementById('cart-discount');
      const discountRow = document.getElementById('cart-discount-row');
      const disc = Math.max(0, Math.round(Number(window.__kahawaCartDiscount || 0)));
      const totals = this.totals(selectedOrderType(), disc);
      const subEl = document.getElementById('cart-subtotal');
      const taxEl = document.getElementById('cart-tax');
      const delEl = document.getElementById('cart-delivery');
      const totEl = document.getElementById('cart-total');
      if (subEl) subEl.textContent = money(totals.subtotal);
      if (taxEl) taxEl.textContent = money(totals.tax);
      if (delEl) delEl.textContent = money(totals.delivery);
      if (discountEl) discountEl.textContent = money(totals.discount);
      if (discountRow) discountRow.classList.toggle('hidden', totals.discount <= 0);
      if (totEl) totEl.textContent = money(totals.total);

      if (window.lucide) window.lucide.createIcons();
      window.dispatchEvent(new CustomEvent('kahawa:cart-page-rendered'));
    },
  };

  // --- Customize modal -----------------------------------------------------

  let activeProduct = null;

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function selectedRadio(name) {
    return document.querySelector(`input[name="${name}"]:checked`);
  }

  function calcUnitPrice() {
    if (!activeProduct) return 0;
    let total = Number(activeProduct.price) || 0;
    if (activeProduct.allowSize) {
      const size = selectedRadio('size');
      if (size) total += Number(size.dataset.extra) || 0;
    }
    if (activeProduct.allowMilk) {
      const milk = selectedRadio('milk');
      if (milk) total += Number(milk.dataset.extra) || 0;
    }
    if (activeProduct.allowShot) {
      const shot = qs('#extra-shot');
      if (shot && shot.checked) total += Number(shot.dataset.extra) || 0;
    }
    return total;
  }

  function currentCustomization() {
    const customization = {};
    if (!activeProduct) return customization;
    if (activeProduct.allowSize) {
      const sizeEl = selectedRadio('size');
      customization.size = sizeEl ? sizeEl.value : 'Regular';
    }
    if (activeProduct.allowMilk) {
      const milkEl = selectedRadio('milk');
      customization.milk = milkEl ? milkEl.value : 'Dairy';
    }
    if (activeProduct.allowShot) {
      customization.extra_shot = !!qs('#extra-shot')?.checked;
    }
    return customization;
  }

  function setOptionVisible(id, show) {
    const el = qs(id);
    if (el) el.classList.toggle('hidden', !show);
  }

  function productFromButton(btn) {
    return {
      id: btn.dataset.productId,
      name: btn.dataset.productName,
      price: btn.dataset.productPrice,
      image: btn.dataset.productImage || '',
      category: btn.dataset.productCategory || '',
      allowSize: btn.dataset.allowSize === '1',
      allowMilk: btn.dataset.allowMilk === '1',
      allowShot: btn.dataset.allowExtraShot === '1',
      taxType: btn.dataset.taxType || 'B',
    };
  }

  function hasOptions(product) {
    return !!(product.allowSize || product.allowMilk || product.allowShot);
  }

  function addPlain(product) {
    KahawaCart.addItem({
      productId: product.id,
      name: product.name,
      image: product.image,
      quantity: 1,
      unitPrice: Number(product.price) || 0,
      taxType: product.taxType || 'B',
      customization: {},
    });
    showToast(`Added ${product.name} to bag`);
  }

  function refreshTotal() {
    const el = qs('#customize-total');
    if (el) el.textContent = String(Math.round(calcUnitPrice()));
  }

  function openModal(product) {
    activeProduct = product;
    const modal = qs('#customize-modal');
    if (!modal) return;

    qs('#customize-title').textContent = product.name;
    qs('#customize-category').textContent = product.category || 'Drink';

    const img = qs('#customize-image');
    const fallback = qs('#customize-image-fallback');
    if (product.image) {
      img.src = product.image;
      img.alt = product.name;
      img.classList.remove('hidden');
      fallback.classList.add('hidden');
    } else {
      img.classList.add('hidden');
      img.removeAttribute('src');
      fallback.classList.remove('hidden');
    }

    setOptionVisible('#customize-size', !!product.allowSize);
    setOptionVisible('#customize-milk', !!product.allowMilk);
    setOptionVisible('#customize-shot', !!product.allowShot);

    const regular = document.querySelector('input[name="size"][value="Regular"]');
    const dairy = document.querySelector('input[name="milk"][value="Dairy"]');
    const shot = qs('#extra-shot');
    if (regular) regular.checked = true;
    if (dairy) dairy.checked = true;
    if (shot) shot.checked = false;

    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('overflow-hidden');
    refreshTotal();
    if (window.lucide) window.lucide.createIcons();
  }

  function closeModal() {
    const modal = qs('#customize-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('overflow-hidden');
    activeProduct = null;
  }

  function showToast(message) {
    const toast = qs('#cart-toast');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.remove('hidden');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.add('hidden'), 2200);
  }

  function addToBag() {
    if (!activeProduct) return;
    const customization = currentCustomization();

    KahawaCart.addItem({
      productId: activeProduct.id,
      name: activeProduct.name,
      image: activeProduct.image,
      quantity: 1,
      unitPrice: calcUnitPrice(),
      taxType: activeProduct.taxType || 'B',
      customization,
    });

    showToast(`Added ${activeProduct.name} to bag`);
    closeModal();
  }

  function bindModal() {
    document.addEventListener('click', (e) => {
      const offerBtn = e.target.closest('.js-add-package');
      if (offerBtn) {
        KahawaCart.addItem({
          packageId: offerBtn.dataset.packageId,
          name: offerBtn.dataset.packageName,
          image: offerBtn.dataset.packageImage || '',
          quantity: 1,
          unitPrice: Number(offerBtn.dataset.packagePrice) || 0,
          taxType: offerBtn.dataset.taxType || 'B',
          customization: { components_label: offerBtn.dataset.packageIncludes || '' },
        });
        showToast(`Added ${offerBtn.dataset.packageName} to bag`);
        return;
      }
      const btn = e.target.closest('.js-open-customize');
      if (!btn) return;
      const product = productFromButton(btn);
      if (!hasOptions(product)) {
        addPlain(product);
        return;
      }
      openModal(product);
    });

    qs('#customize-close')?.addEventListener('click', closeModal);
    qs('#customize-backdrop')?.addEventListener('click', closeModal);
    qs('#customize-add')?.addEventListener('click', addToBag);

    document.addEventListener('change', (e) => {
      if (!qs('#customize-modal') || qs('#customize-modal').classList.contains('hidden')) return;
      if (e.target.matches('input[name="size"], input[name="milk"], #extra-shot')) {
        refreshTotal();
      }
    });
  }

  function bindCartPage() {
    document.getElementById('cart-page-items')?.addEventListener('click', (e) => {
      const qtyBtn = e.target.closest('.js-cart-qty');
      if (qtyBtn) {
        const key = qtyBtn.dataset.key;
        const delta = parseInt(qtyBtn.dataset.delta, 10) || 0;
        const cart = KahawaCart.get();
        const current = cart[key]?.quantity || 0;
        KahawaCart.setQuantity(key, current + delta);
        return;
      }
      const removeBtn = e.target.closest('.js-cart-remove');
      if (removeBtn) {
        KahawaCart.removeItem(removeBtn.dataset.key);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    KahawaCart.updateBadge();
    KahawaCart.renderCartPage();
    bindModal();
    bindCartPage();

    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      closeModal();
    });
  });

  window.KahawaCart = KahawaCart;
})(window, document);
