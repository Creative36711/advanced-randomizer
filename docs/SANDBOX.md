# Песочница Arena: подъём и инструменты

Песочница сбрасывается между сессиями: `/tmp` обнуляется, остаются только
файлы внутри репозитория. Поэтому всё, что нужно для работы, лежит здесь —
в `tools/sandbox/` — и ставится одной командой.

## Одна команда

```bash
tools/sandbox/bootstrap.sh          # поставить всё нужное
tools/sandbox/bootstrap.sh --check  # только проверить, что уже есть
```

Скрипт идемпотентен: он смотрит на диск и качает только отсутствующее.
Повторный запуск — почти мгновенный.

| Что | Куда | Зачем |
|---|---|---|
| Godot 4.7.2 + SwiftShader | `/tmp/godotbin` | движок; единственный рендер без GPU |
| venv импортёра | `/tmp/impvenv` | Pillow, fonttools, defusedxml для `importer/` |
| медиа-окружение | `/tmp/mediaenv` | Pillow + numpy для хромакея |
| Blender 4.5.3 (bpy) | `/tmp/bpyenv` + стабы | 3D, рендер, W3D→glTF без установки Blender |

## Godot без GPU

В песочнице нет `/dev/dri` и `DISPLAY` пуст. Godot рендерит **offscreen на
Vulkan через SwiftShader** (CPU). Отсюда два жёстких правила:

- `--headless` **не рисует кадры вообще** — для скриншотов он бесполезен;
- обязательны переменные из `bootstrap.sh`:
  `VK_ICD_FILENAMES=…/vk_swiftshader_icd.json` и `LD_LIBRARY_PATH=…/godotbin`.

Источник Godot — `Creative36711/synapse`, `tools/godot/dist`: два xz-куска
бинарника + SwiftShader. Хэши сверяются с `SHA256SUMS` перед распаковкой.

## Скриншоты рандомайзера

```bash
tools/sandbox/shots.sh /tmp/play            # → /tmp/shots
tools/sandbox/shots.sh /tmp/play docs/shots # → в свой каталог
```

Пишет `randomizer_host.png`, `randomizer_guest.png`, `lobby.png`,
`lobby_randomizer.png` — пиксель в пиксель (stretch выключен в скрипте).

**Скрипт сам проверяет геометрию** и падает с ненулевым кодом, если окно не
вмещает панель, выходит за пределы лобби или кнопка вылезает за край. Это не
формальность: оба дефекта («панели нужно 536×267, а окно 490×225» и «кнопка
шириной 198px при остатке 152px») были видны только на снимках и проходили
мимо тестов движка.

## Blender как pip-модуль

`download.blender.org` из песочницы недоступен, зато открыт `pypi.org`:
`bpy==4.5.3` — это целый Blender 4.5.3 LTS как модуль (355 МБ, CPython 3.11).

```bash
LD_LIBRARY_PATH=/tmp/bpystubs /tmp/bpyenv/bin/python your_script.py
```

Колесо линкуется с X11/GL, которых в песочнице нет. `bpy_stubs.py` собирает
пустые разделяемые библиотеки с нужными символами — этого достаточно, чтобы
`import bpy` прошёл, **Cycles рендерил на CPU**, а glTF экспортировался.
Проверено: рендер 128×128 за 0.27 с, `export_scene.gltf` → корректный GLB.

Источник скриптов — `Creative-textile/vault`, коммит `dba810a8ee` (до D-125,
которое удалило песочничный контур как «локальный»). Скрипты перенесены без
изменения логики.

## Хромакей

```bash
/tmp/mediaenv/bin/python tools/sandbox/cutout_chromakey.py in.png out.png --mode auto --crop
```

Строгий зелёный ключ (`#00FF00`): пиксель — фон, только если зелёный > 140,
доминирует над остальными каналами и это **не** бирюза (`blue < 75% green`).
Поэтому синие и бирюзовые детали не вырезаются. `--heal` чинит иконки,
испорченные старыми вырезками.

Проверено сквозным тестом: генерация на `#00FF00` → вырезание → RGBA с чистым
краем (28 % прозрачных, 0 % полупрозрачного ореола, без зелёной каймы).

Когда рисовать SVG, а когда генерировать изображение — `docs/ART-PIPELINE.md`.

## Проверка установки игры без её передачи

```bash
python3 tools/retail_fingerprint.py "D:/Games/BFME2" --json bfme2.json
python3 tools/retail_fingerprint.py "D:/RotWK" --game rotwk --sizes-only
```

Сверяет каждый архив с `contracts/*-archives.json` (путь, размер, md5) и
называет версию игры по числам. Это заменяет передачу гигабайтов: отчёт —
несколько килобайт. Подробнее — `docs/TESTING-WITHOUT-FILES.md`.
