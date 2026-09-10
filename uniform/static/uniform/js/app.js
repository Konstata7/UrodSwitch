/* ============================================================
   Uniform Applicator — логика одностраничника (vanilla JS).

   Что делает:
     1. показывает локальный предпросмотр выбранных файлов;
     2. отправляет форму через fetch (AJAX) с CSRF-токеном;
     3. по ответу показывает результат / сообщение об ошибке.
   ============================================================ */
'use strict';

(function () {
    const form = document.getElementById('uniform-form');
    if (!form) return;

    const skinInput = document.getElementById('id-skin');
    const uniformInput = document.getElementById('id-uniform');
    const previewSkin = document.getElementById('preview-skin');
    const previewUniform = document.getElementById('preview-uniform');
    const submitBtn = document.getElementById('submit-btn');
    const statusEl = document.getElementById('status');
    const jsMessage = document.getElementById('js-message');
    const resultSection = document.getElementById('result');
    const resultImage = document.getElementById('result-image');
    const downloadLink = document.getElementById('download-link');
    const blockbenchLink = document.getElementById('blockbench-btn');
    const resetBtn = document.getElementById('reset-btn');

    /* ---------- локальный предпросмотр ---------- */
    function bindPreview(input, image) {
        input.addEventListener('change', function () {
            const file = input.files && input.files[0];
            if (!file) { image.hidden = true; return; }
            const url = URL.createObjectURL(file);
            image.onload = function () { URL.revokeObjectURL(url); };
            image.src = url;
            image.hidden = false;
        });
    }
    bindPreview(skinInput, previewSkin);
    bindPreview(uniformInput, previewUniform);

    /* ---------- сообщения ---------- */
    function showMessage(text) {
        if (!text) { jsMessage.hidden = true; jsMessage.textContent = ''; return; }
        jsMessage.textContent = text;
        jsMessage.hidden = false;
    }

    function setBusy(busy) {
        submitBtn.disabled = busy;
        statusEl.hidden = !busy;
    }

    /* ---------- отправка ---------- */
    form.addEventListener('submit', function (event) {
        event.preventDefault();
        showMessage('');

        if (!skinInput.files.length || !uniformInput.files.length) {
            showMessage('Загрузите оба файла: скин и форму.');
            skinInput.focus();
            return;
        }

        setBusy(true);
        const body = new FormData(form);

        fetch(form.action, {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: body,
            credentials: 'same-origin',
        })
            .then(function (response) {
                return response.json().then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function (res) {
                if (res.ok && res.data.ok) {
                    resultImage.src = res.data.url;
                    downloadLink.href = res.data.url;
                    downloadLink.download = res.data.download || 'uniform_applicator.png';
                    if (blockbenchLink && res.data.blockbench) {
                        blockbenchLink.href = res.data.blockbench;
                    }
                    resultSection.hidden = false;
                    resultSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                } else {
                    resultSection.hidden = true;
                    showMessage((res.data && res.data.error) || 'Не удалось обработать файлы.');
                }
            })
            .catch(function () {
                resultSection.hidden = true;
                showMessage('Сетевая ошибка. Проверьте, что сервер запущен, и попробуйте снова.');
            })
            .finally(function () {
                setBusy(false);
            });
    });

    /* ---------- «Заново» ---------- */
    resetBtn.addEventListener('click', function () {
        form.reset();
        [previewSkin, previewUniform].forEach(function (img) { img.hidden = true; img.src = ''; });
        resultSection.hidden = true;
        resultImage.removeAttribute('src');
        if (blockbenchLink) blockbenchLink.href = '#';
        showMessage('');
    });
})();
