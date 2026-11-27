/**
 * Utilidades de UI globales: modales de confirmación, prompt y toast.
 *
 * Reemplazan a los diálogos nativos del navegador (alert / confirm / prompt)
 * por componentes propios con el mismo estilo del sistema (Tailwind).
 *
 * API (disponible en window de forma global):
 *   - uiConfirm(message, opts?)  -> Promise<boolean>
 *   - uiPrompt(opts)             -> Promise<string | null>  (null = cancelado)
 *   - uiToast(message, type?)    -> void   (type: 'success' | 'error' | 'warning')
 */
(function () {
    'use strict';

    let confirmResolve = null;
    let promptResolve = null;

    function ensureContainer() {
        let el = document.getElementById('ui-modals');
        if (el) return el;

        el = document.createElement('div');
        el.id = 'ui-modals';
        el.innerHTML = `
            <div id="ui-confirm" class="fixed inset-0 z-[60] hidden items-center justify-center p-4">
                <div class="absolute inset-0 bg-gray-900/60" data-close="ui-confirm"></div>
                <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
                    <h3 id="ui-confirm-title" class="text-lg font-bold text-gray-900 mb-2">Confirmar Acción</h3>
                    <p id="ui-confirm-message" class="text-sm text-gray-600 mb-6 whitespace-pre-wrap"></p>
                    <div class="flex justify-end gap-3">
                        <button id="ui-confirm-cancel" class="px-4 py-2 text-gray-600 hover:text-gray-800 text-sm font-medium rounded-lg">Cancelar</button>
                        <button id="ui-confirm-ok" class="px-4 py-2 bg-blue-900 text-white rounded-lg text-sm font-semibold">Confirmar</button>
                    </div>
                </div>
            </div>
            <div id="ui-prompt" class="fixed inset-0 z-[60] hidden items-center justify-center p-4">
                <div class="absolute inset-0 bg-gray-900/60" data-close="ui-prompt"></div>
                <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
                    <h3 id="ui-prompt-title" class="text-lg font-bold text-gray-900 mb-3"></h3>
                    <label id="ui-prompt-label" class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1"></label>
                    <input id="ui-prompt-input" class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none" />
                    <div class="flex justify-end gap-3 mt-6">
                        <button id="ui-prompt-cancel" class="px-4 py-2 text-gray-600 hover:text-gray-800 text-sm font-medium rounded-lg">Cancelar</button>
                        <button id="ui-prompt-ok" class="px-4 py-2 bg-blue-900 text-white rounded-lg text-sm font-semibold">Aceptar</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(el);

        // Confirm
        el.querySelector('#ui-confirm-ok').addEventListener('click', function () {
            hide('ui-confirm');
            if (confirmResolve) { confirmResolve(true); confirmResolve = null; }
        });
        el.querySelector('#ui-confirm-cancel').addEventListener('click', function () {
            hide('ui-confirm');
            if (confirmResolve) { confirmResolve(false); confirmResolve = null; }
        });

        // Prompt
        el.querySelector('#ui-prompt-ok').addEventListener('click', function () {
            hide('ui-prompt');
            if (promptResolve) { promptResolve(el.querySelector('#ui-prompt-input').value); promptResolve = null; }
        });
        el.querySelector('#ui-prompt-cancel').addEventListener('click', function () {
            hide('ui-prompt');
            if (promptResolve) { promptResolve(null); promptResolve = null; }
        });
        el.querySelector('#ui-prompt-input').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') el.querySelector('#ui-prompt-ok').click();
        });

        // Backdrop
        el.querySelectorAll('[data-close]').forEach(function (bg) {
            bg.addEventListener('click', function () {
                var id = bg.getAttribute('data-close');
                hide(id);
                if (id === 'ui-confirm' && confirmResolve) { confirmResolve(false); confirmResolve = null; }
                if (id === 'ui-prompt' && promptResolve) { promptResolve(null); promptResolve = null; }
            });
        });

        return el;
    }

    function show(id) {
        ensureContainer();
        var m = document.getElementById(id);
        m.classList.remove('hidden');
        m.classList.add('flex');
    }

    function hide(id) {
        var m = document.getElementById(id);
        if (m) { m.classList.add('hidden'); m.classList.remove('flex'); }
    }

    // --- Confirmación (reemplaza a confirm()) ---
    window.uiConfirm = function (message, opts) {
        opts = opts || {};
        ensureContainer();
        document.getElementById('ui-confirm-title').innerText = opts.title || 'Confirmar Acción';
        document.getElementById('ui-confirm-message').innerText = message;
        var okBtn = document.getElementById('ui-confirm-ok');
        okBtn.innerText = opts.confirmText || 'Confirmar';
        okBtn.className = 'px-4 py-2 text-white rounded-lg text-sm font-semibold ' +
            (opts.danger ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-900 hover:bg-blue-800');
        show('ui-confirm');
        return new Promise(function (resolve) { confirmResolve = resolve; });
    };

    // --- Prompt (reemplaza a prompt()) ---
    window.uiPrompt = function (opts) {
        opts = opts || {};
        ensureContainer();
        document.getElementById('ui-prompt-title').innerText = opts.title || 'Ingrese un valor';
        var label = document.getElementById('ui-prompt-label');
        if (opts.label) { label.innerText = opts.label; label.classList.remove('hidden'); }
        else { label.classList.add('hidden'); }
        var input = document.getElementById('ui-prompt-input');
        input.type = opts.type || 'text';
        input.value = (opts.value !== undefined && opts.value !== null) ? opts.value : '';
        input.placeholder = opts.placeholder || '';
        input.required = opts.required !== false;
        document.getElementById('ui-prompt-ok').innerText = opts.confirmText || 'Aceptar';
        show('ui-prompt');
        setTimeout(function () { input.focus(); }, 50);
        return new Promise(function (resolve) { promptResolve = resolve; });
    };

    // --- Toast (reemplaza a alert() para mensajes de error/info) ---
    window.uiToast = function (message, type) {
        type = type || 'success';
        var existing = document.querySelectorAll('.custom-toast');
        existing.forEach(function (t) { t.remove(); });

        var toast = document.createElement('div');
        var color = type === 'error' ? 'bg-red-600' : (type === 'warning' ? 'bg-amber-600' : 'bg-green-600');
        toast.className = 'custom-toast fixed top-5 right-5 ' + color +
            ' text-white px-6 py-4 rounded-lg shadow-xl transition-all duration-500 z-[70] max-w-md whitespace-pre-wrap font-medium text-sm border-l-4 border-white/30';
        toast.innerText = message;
        document.body.appendChild(toast);

        requestAnimationFrame(function () {
            toast.style.transform = 'translateY(10px)';
            toast.style.opacity = '1';
        });

        setTimeout(function () {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-20px)';
            setTimeout(function () { toast.remove(); }, 500);
        }, 5000);
    };
})();
