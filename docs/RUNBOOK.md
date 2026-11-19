# RUNBOOK: работа над Randomizer на OpenBFME

Всё, что нужно новой сессии, в одном месте. Проверено на практике.

## 0. Первое действие в любой новой сессии

Песочница сбрасывается: `/tmp` пуст, Godot, cmake и bpy исчезли. Одна команда
возвращает всё:

```bash
tools/sandbox/bootstrap.sh          # ~75 секунд: cmake+ninja, Godot 4.7.2, Blender, медиа
tools/sandbox/bootstrap.sh --check  # что уже есть, без установки
```

Затем движок:

```bash
tools/sandbox/build_engine.sh --check   # что собрано
tools/sandbox/build_engine.sh --core    # только ядро, ~15 мин на 2 ядрах
tools/sandbox/build_engine.sh           # GDExtension, 40+ мин (godot-cpp)
```

## 1. Где что лежит

| Путь | Что | Размер |
|---|---|---|
| `upstream/` | снимок `Open-BFME/openbfme-godot` на 18.11.2026 | 71 МБ, 4159 файлов |
| `upstream/engine/` | C++ движок (540 тыс. строк) — здесь наша фича | |
| `upstream/godot/` | UI на GDScript (289 файлов) | |
| `tools/sandbox/bootstrap.sh` | окружение одной командой | |
| `tools/sandbox/build_engine.sh` | сборка движка с обходом дефектов | |
| `tools/big_roundtrip.py` | разбор/сборка SAGE `.big` | |
| `docs/RESEARCH.md` | что Randomizer может дать только на Godot | |

## 2. Дефекты upstream, которые уже обойдены

Сборка на GCC 12 падает «из коробки». Это **не наши ошибки**:

1. **185 заголовков** используют `size_t` без `<cstddef>`.
   → `build_engine.sh` добавляет `-DCMAKE_CXX_FLAGS="-include cstddef"`.
2. **`engine/thirdparty/godot-cpp` — пустой сабмодуль.**
   → скрипт качает его по пину `507ed9d8…` через codeload.
3. `SHA256SUMS` для Godot **не содержит** хеша склеенного `.xz` — только
   частей и распакованного бинарника. → сверил в `bootstrap.sh` именно их.

## 3. Как запустить игру

Нужны установки RotWK 2.01 и BFME2 1.06 **полного размера**. Движок сверяет
каждый архив по MD5 и **«There is no opt-out»**.

```bash
export ROTWK_INSTALL=/path/to/RotWK
export BFME2_INSTALL=/path/to/BFME2
VK_ICD_FILENAMES=/tmp/godotbin/vk_swiftshader_icd.json \
LD_LIBRARY_PATH=/tmp/godotbin \
/tmp/godotbin/godot --path upstream/godot
```

GPU в песочнице нет: рендер идёт через **SwiftShader на CPU**.
`--headless` **кадров не рисует вообще** — для скриншотов он бесполезен.

## 4. Что нужно из файлов игры

Эталон — `upstream/engine/data/retail-archives/*.json`. Записей:

- RotWK 2.01: **106 архивов**, из них 4 крупных, которых часто нет:
  `lang/EnglishAudio.big` (452 МБ), `W3D.big` (227), `Textures2.big` (218),
  `Textures3.big` (133);
- BFME2 1.06: **107 архивов, 4 ГБ**. Без него движок не смонтирует установку.

Сверить свою установку с эталоном:

```bash
python3 - <<'PY'
import json, hashlib, os
d = json.load(open('upstream/engine/data/retail-archives/rotwk-201-english-archives.json'))
root = os.environ['ROTWK_INSTALL']
disk = {os.path.relpath(os.path.join(dp,f), root).replace('\\','/').lower(): os.path.join(dp,f)
        for dp,_,fs in os.walk(root) for f in fs}
ok = bad = 0
for a in d['archives']:
    p = disk.get(a['path'].lower())
    if not p or os.path.getsize(p) != a['size'] or \
       hashlib.md5(open(p,'rb').read()).hexdigest() != a['md5']:
        bad += 1; print('  не совпало:', a['path'])
    else:
        ok += 1
print(f'совпало {ok} из {len(d["archives"])}')
PY
```

## 5. Формат SAGE .big — что мы выяснили

`tools/big_roundtrip.py` собирает архивы **байт-в-байт** (проверено на 18
архивах RotWK). Ключевое, чего нет в общедоступных описаниях:

- **`OffsetFirst` — начало ДАННЫХ**, а не списка записей;
- **`OffsetFirst` может врать** (`data1.big`: в заголовке 750, данные с 751) —
  начало берётся из первой записи;
- между списком и данными бывает **подпись сборщика** (`L219`, `L253`), причём
  в разных местах; сохраняется как есть;
- бывают **дубликаты имён** и **хвостовой padding**.

## 6. Куда идти дальше

Три уровня «вау» из `docs/RESEARCH.md`, от достижимого к невозможному в SAGE:

1. **Перемешивание командных панелей** — данные + `CommandSet`, уже полноценный режим;
2. **Живой драфт** — между волнами выбор из 3 карт (`set_paused` + UI на GDScript);
3. **Зрелищные события** — метеор, нашествие, камера (`cast_special_power`, FX).

Шаблон для правила в меню уже есть в коде — **`Legendary Heroes`**:
```
MpGameRules.h → SkirmishGameSetup → AptSkirmishRules → LoadScreenInfo → логика
```
Это правило OpenBFME, которого нет в retail. Делаем по его образцу.

## 7. Локализация

Retail-текст приходит из CSF игрока — его не переводим. Переводим **только своё**.
Стандарт upstream (`docs/L10N.md`):

```json
{"@@locale": "ru", "randomizer.hud.mutation_title": "Мутация"}
```

`en.json` — источник, `ru.json` — перевод, id вида `<consumer>.<area>.<name>`.

## 8. Ограничения песочницы (проверено)

| Что | Итог |
|---|---|
| `drive.google.com`, `googleapis.com` | ✗ заблокированы |
| Google Drive коннектор | ✓ работает, но **≤100 МБ** на файл |
| `release-assets.githubusercontent.com`, S3 | ✗ заблокированы |
| `codeload`, `api.github.com` | ✓ работают |
| `git-lfs` | ✗ поставить нельзя |
| Форк репозитория | ✗ App не может форкать (403) |
| apt без root | ✗ |
