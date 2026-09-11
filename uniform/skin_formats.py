"""
Форматы скинов Minecraft, между которыми выбирает пользователь.

Формат влияет на две вещи:

* **разметку формы (uniform)** — у slim-скинов руки на пиксель уже, поэтому
  области рук в текстуре другие (см. ``ARM_MAIN`` в ``uniform/constants.py``);
* **модель игрока в Blockbench** — classic открывается как Steve, slim как Alex
  (см. ``SKIN_MODELS`` в ``uniform/blockbench.py``).

Формат выбирается в форме (поле ``skin_format``) до загрузки файлов и дальше
идёт через всю обработку: ``views._process_upload`` → ``services.compose`` →
``blockbench.build_project``.
"""

#: Широкие руки (4 пикселя), модель Steve.
CLASSIC = "classic"

#: Узкие руки (3 пикселя), модель Alex.
SLIM = "slim"

#: Все поддерживаемые форматы — в порядке отображения в интерфейсе.
ALL = (CLASSIC, SLIM)

#: Формат по умолчанию (для вызовов без явного выбора).
DEFAULT = CLASSIC

#: Подписи для интерфейса.
LABELS = {
    CLASSIC: "Classic",
    SLIM: "Slim",
}

#: Пояснение к подписи: какие руки и какая модель откроется в Blockbench.
DESCRIPTIONS = {
    CLASSIC: "широкие руки, 4 пикселя — модель Steve",
    SLIM: "узкие руки, 3 пикселя — модель Alex",
}


def is_valid(value: object) -> bool:
    """True, если значение — известный формат скина."""
    return value in ALL
