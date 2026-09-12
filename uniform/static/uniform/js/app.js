/* ============================================================
   UrodSwitch — логика одностраничника (vanilla JS).

   Что делает:
     1. показывает локальный предпросмотр выбранных файлов;
     2. определяет формат скина по файлу (classic/slim) и подставляет его
        в шаг 1 — тем же правилом, что и на сервере;
     3. отправляет форму через fetch (AJAX) с CSRF-токеном;
     4. по ответу показывает результат / сообщение об ошибке.
   ============================================================ */
'use strict';

(function () {
    const form = document.getElementById('uniform-form');
    if (!form) return;

    /* Области, которые есть только у classic-скина: у slim руки на пиксель уже,
       и эти пиксели не используются. Если в каждой области закрашены все
       пиксели — classic, иначе slim. То же правило на сервере:
       uniform/constants.CLASSIC_ONLY_REGIONS + services.detect_skin_format. */
    const CLASSIC_ONLY_REGIONS = [
        [50, 16, 51, 19],
        [54, 20, 55, 31],
        [42, 48, 43, 51],
        [46, 52, 47, 63],
    ];

    const formatInputs = Array.prototype.slice.call(
        form.querySelectorAll('input[name="skin_format"]')
    );
    const formatChoice = document.getElementById('format-choice');
    const formatStatus = document.getElementById('format-status');
    const skinInput = document.getElementById('id-skin');
    const uniformInput = document.getElementById('id-uniform');
    const previewSkin = document.getElementById('preview-skin');
    const previewUniform = document.getElementById('preview-uniform');
    const submitBtn = document.getElementById('submit-btn');
    const statusEl = document.getElementById('status');
    const jsMessage = document.getElementById('js-message');
    const resultSection = document.getElementById('result');
    const resultImage = document.getElementById('result-image');
    const resultFormat = document.getElementById('result-format');
    const downloadLink = document.getElementById('download-link');
    const blockbenchLink = document.getElementById('blockbench-btn');
    const resetBtn = document.getElementById('reset-btn');
    const nickSkin = document.getElementById('nick-skin');
    const nickInput = document.getElementById('id-nickname');
    const nickConfirmed = document.getElementById('skin-nickname');
    const nickBtn = document.getElementById('nick-btn');
    const nickStatus = document.getElementById('nick-status');
    const resultNote = document.getElementById('result-note');

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

    /* ---------- выбранный формат скина (шаг 1) ---------- */
    function chosenFormat() {
        const checked = formatInputs.find(function (input) { return input.checked; });
        return checked ? checked.value : '';
    }

    function selectFormat(value) {
        const input = formatInputs.find(function (item) { return item.value === value; });
        if (input) input.checked = true;
    }

    function formatLabel(value) {
        const input = formatInputs.find(function (item) { return item.value === value; });
        if (!input) return value || '';
        const option = input.closest('.format-option');
        const title = option && option.querySelector('.format-option-title');
        const hint = option && option.querySelector('.format-option-hint');
        return title ? title.textContent + ' — ' + (hint ? hint.textContent : '') : value;
    }

    /** Пишем в шаг 1, откуда взялся формат: из скина или выбран вручную. */
    function showFormatStatus(text, isManual) {
        if (!formatStatus) return;
        formatStatus.textContent = text || '';
        formatStatus.hidden = !text;
        formatStatus.classList.toggle('is-manual', !!isManual);
    }

    /**
     * Определяет формат скина по картинке тем же правилом, что и сервер.
     * Возвращает 'classic' | 'slim' | '' (если картинку прочитать не удалось).
     */
    function detectSkinFormat(file) {
        return new Promise(function (resolve) {
            let url;
            try {
                url = URL.createObjectURL(file);
            } catch (err) {
                resolve('');
                return;
            }

            const img = new Image();

            img.onload = function () {
                URL.revokeObjectURL(url);
                try {
                    const w = img.naturalWidth;
                    const h = img.naturalHeight;
                    // Как и на сервере: HD-скины (кратные 64×64) приводим к 64×64.
                    if (!w || !h || w % 64 || h % 64) { resolve(''); return; }

                    const canvas = document.createElement('canvas');
                    canvas.width = 64;
                    canvas.height = 64;
                    const ctx = canvas.getContext('2d');
                    ctx.imageSmoothingEnabled = false;
                    ctx.drawImage(img, 0, 0, 64, 64);
                    const data = ctx.getImageData(0, 0, 64, 64).data;

                    const painted = function (x, y) {
                        return data[(y * 64 + x) * 4 + 3] > 0;
                    };
                    const filled = function (region) {
                        for (let x = region[0]; x <= region[2]; x++) {
                            for (let y = region[1]; y <= region[3]; y++) {
                                if (!painted(x, y)) return false;
                            }
                        }
                        return true;
                    };

                    const classic = CLASSIC_ONLY_REGIONS.every(filled);
                    resolve(classic ? 'classic' : 'slim');
                } catch (err) {
                    resolve('');   // нет canvas/getImageData — определит сервер
                }
            };
            img.onerror = function () { URL.revokeObjectURL(url); resolve(''); };
            img.src = url;
        });
    }

    /** Определяем формат по выбранному файлу и подставляем его в шаг 1. */
    function detectFormatFromFile(file) {
        if (!file) return;
        detectSkinFormat(file).then(function (detected) {
            if (!detected) return;
            // Файл мог уже смениться, пока читалась картинка.
            if (!skinInput.files.length || skinInput.files[0] !== file) return;
            selectFormat(detected);
            showFormatStatus('По скину определился формат ' + formatLabel(detected) + '.', false);
        });
    }

    /* ---------- скин по нику игрока ---------- */
    function showNickStatus(text, isError) {
        if (!nickStatus) return;
        nickStatus.textContent = text || '';
        nickStatus.hidden = !text;
        nickStatus.classList.toggle('is-error', !!isError);
    }

    /* Предпросмотр скина один для обоих источников: и файл, и ник
       показываются в блоке «2. Скин». */
    function showSkinPreview(src) {
        if (!src) {
            previewSkin.removeAttribute('src');
            previewSkin.hidden = true;
            return;
        }
        previewSkin.src = src;
        previewSkin.hidden = false;
    }

    /** Забыть найденный по нику скин (перед тем как взять другой источник). */
    function forgetNicknameSkin() {
        if (nickConfirmed) nickConfirmed.value = '';
    }

    /** Есть ли скин: файл или ник (подтверждённый либо только вписанный). */
    function hasNickname() {
        if (nickConfirmed && nickConfirmed.value.trim()) return true;
        return !!(nickInput && nickInput.value.trim());
    }

    function lookupNickname() {
        const nickname = (nickInput.value || '').trim();

        if (!nickname) {
            showNickStatus('Введите ник игрока.', true);
            nickInput.focus();
            return;
        }
        if (!/^[A-Za-z0-9_]{1,16}$/.test(nickname)) {
            showNickStatus('Ник может состоять из латинских букв, цифр и «_».', true);
            nickInput.focus();
            return;
        }

        const url = nickSkin.dataset.lookupUrl.replace('NICKNAME', encodeURIComponent(nickname));
        nickBtn.disabled = true;
        showNickStatus('Ищем скин игрока…', false);

        fetch(url, { credentials: 'same-origin' })
            .then(function (response) {
                return response.json().then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function (res) {
                if (!res.ok || !res.data.ok) {
                    showNickStatus((res.data && res.data.error) || 'Не удалось получить скин.', true);
                    return;
                }
                // Запоминаем ник отдельно от поля ввода: скин остаётся загруженным,
                // даже если поле потом очистят или браузер потеряет его значение.
                if (nickConfirmed) nickConfirmed.value = res.data.nickname;
                nickInput.value = res.data.nickname;
                // Показываем найденный скин там же, где скин из файла.
                showSkinPreview(res.data.skin);
                // Формат скина игрока известен точно (его сообщает Mojang).
                selectFormat(res.data.format);
                showFormatStatus('По скину игрока определился формат '
                    + formatLabel(res.data.format) + '.', false);
                // Скин либо файлом, либо по нику — выбранный файл больше не нужен.
                skinInput.value = '';
                showNickStatus(res.data.nickname + ' — ' + res.data.format_label, false);
            })
            .catch(function () {
                showNickStatus('Сетевая ошибка. Проверьте соединение и попробуйте снова.', true);
            })
            .finally(function () {
                nickBtn.disabled = false;
            });
    }

    if (nickBtn) nickBtn.addEventListener('click', lookupNickname);
    if (nickInput) {
        nickInput.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                lookupNickname();
            }
        });
        // Пустое поле ничего не отменяет: уже найденный скин остаётся загруженным.
        // А вот другой ник означает, что найденный скин больше не подходит.
        nickInput.addEventListener('input', function () {
            const typed = (nickInput.value || '').trim();
            const confirmed = nickConfirmed ? nickConfirmed.value.trim() : '';

            if (!typed || (confirmed && typed.toLowerCase() === confirmed.toLowerCase())) return;

            forgetNicknameSkin();
            if (!skinInput.files.length) showSkinPreview('');  // старый скин больше не наш
            showNickStatus('Ник изменён — нажмите «Найти скин», чтобы взять новый скин.', false);
        });
    }

    skinInput.addEventListener('change', function () {
        if (!skinInput.files.length) return;
        // Файл и ник — взаимоисключающие источники скина.
        if (nickInput) nickInput.value = '';
        forgetNicknameSkin();
        showNickStatus('', false);
        // Формат определяем по самому файлу скина.
        detectFormatFromFile(skinInput.files[0]);
    });

    // Ручной выбор формата: он главнее автоопределения (сервер это учтёт).
    formatInputs.forEach(function (input) {
        input.addEventListener('change', function () {
            if (!input.checked) return;
            showFormatStatus('Формат выбран вручную: ' + formatLabel(input.value) + '.', true);
        });
    });

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

        const hasFile = skinInput.files.length > 0;

        // Скин — либо файл, либо ник игрока.
        if (!hasFile && !hasNickname()) {
            showMessage('Скин не выбран: загрузите файл в блок «2. Скин» '
                + 'или впишите ник и нажмите «Найти скин».');
            skinInput.focus();
            return;
        }

        // Формат можно не выбирать: он определяется по скину (сервер сделает это
        // и сам). Выбранный вручную вариант главнее автоопределения.
        if (!uniformInput.files.length) {
            showMessage('Загрузите форму: PNG 64×64 на прозрачном фоне.');
            uniformInput.focus();
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
                    downloadLink.download = res.data.download || 'urodswitch.png';
                    if (resultFormat) {
                        resultFormat.textContent = res.data.format_label || '';
                        resultFormat.hidden = !res.data.format_label;
                    }
                    if (resultNote) {
                        resultNote.textContent = res.data.format_note || '';
                        resultNote.hidden = !res.data.format_note;
                    }
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
        forgetNicknameSkin();
        showFormatStatus('', false);
        resultSection.hidden = true;
        resultImage.removeAttribute('src');
        if (resultFormat) { resultFormat.textContent = ''; resultFormat.hidden = true; }
        if (resultNote) { resultNote.textContent = ''; resultNote.hidden = true; }
        showNickStatus('', false);
        if (blockbenchLink) blockbenchLink.href = '#';
        showMessage('');
    });
})();
