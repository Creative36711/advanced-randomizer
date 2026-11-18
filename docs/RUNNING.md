# Как запустить и протестировать Advanced Randomizer

> **Обычному игроку это руководство не нужно.** Дважды щёлкните
> `launcher/start/AdvancedRandomizer.cmd` — лаунчер сам скачает движок и
> инструменты, сконвертирует ваши файлы и запустит игру. Ниже — ручной путь
> для разработки и разбора поломок.

## Главное, что нужно понять

В этом репозитории **нет движка**. Здесь только наши изменения поверх
[OpenBFME `legacy-final`](https://github.com/Open-BFME/openbfme-godot/tree/bf06a22baab9713ca51cfa03d017534e3b4f752c)
(ветка с GDScript-схваткой) и скрипт сборки. Поэтому «перекинуть пару файлов в
папку openBFME» не получится: движок у тебя в руках уже есть, но наша версия — это
*пересобранное* дерево из нашего патча. Отдельная папка `openBFME` (та, что ты
уже качал) нам не нужна и трогать её не надо.

Также важно: `legacy-final` — это историческая GDScript-ветка, она **читает данные
RotWK 2.02 v9.7.7** (а не 2.01). Поэтому «чистый» 2.01 без патча 2.02 не подойдёт,
и конвертер из текущего C#-main, который ты, возможно, уже гонял, тоже не подойдёт
(у него другой формат бандлов).

## Что нужно

| Что | Зачем |
|---|---|
| Python 3.9+, Git | собрать дерево (`tools/prepare.py`) |
| Godot **4.7.2** (не 4.6 и не 4.8) | движок, которым проверялись все тесты |
| Лицензионные BFME2 1.06 + RotWK 2.01 + **Patch 2.02 v9.7.7** | контент: фракции, карты, HUD |
| Windows | штатный путь импортёра в upstream — Windows-скрипты; под Linux — Wine (см. `docs/LAUNCHER_LINUX_WINE.md` upstream) |

## Шаг 1. Собрать дерево

```sh
cd advanced-randomizer
python3 tools/prepare.py            # создаст build/openbfme/
```

Скрипт скачает архив закреплённого коммита, сверит SHA-256, наложит
`patches/skirmish.patch` и скопирует `game/` (весь режим). Существующий
`build/openbfme` он перезаписывать откажется — это защита от затирания
сконвертированных пакетов, поэтому при повторной сборке указывай новый каталог:
`--output build/openbfme-2`.

Первая проверка, что дерево живое (розничные файлы не нужны):

```sh
godot --headless --path build/openbfme/game --editor --import
godot --headless --path build/openbfme/game --quit-after 120 -s res://tests/randomizer_core_test.gd
```

Ожидаемо: `RANDOMIZER_CORE ok=true templates=96`.

## Шаг 2. Сконвертировать свои розничные файлы

Импортёр живёт в собранном дереве: `build/openbfme/importer`, `build/openbfme/tools`,
скрипты `run_importer.bat` / `run_rotwk_one_button.bat`. Он **читает твою установку
и ничего в ней не меняет**, результат кладёт в `build/openbfme/workspace/`.

Для теста Randomizer хватит одной фракции Men + карты Fords of Isen II (профиль
`men-fords-v0`), но режим рассчитан на все семь — по возможности конвертируй все:

```bat
run_rotwk_full_content.bat "D:\Games\RotWK" --bfme2-install "D:\Games\BFME2" --select
```

или путь «одной кнопкой» (rotwk systems + карты + публикация):

```bat
run_rotwk_one_button.bat "D:\Games\RotWK" --convert-factions --multi-map --build --publish
```

Если скрипты ругаются на версию — значит установлен не 2.02 v9.7.7; поставь патч
(он кладётся поверх 2.01, отдельной копией игры поверх не трогая).

Проверка: в `build/openbfme/workspace/content-packs/selection.json` появился
выбранный пак, а в логе `ContentDB` при старте — не нули:
`[ContentDB] playable: factions=7 ... units=... structures=...`.

## Шаг 3. Играть

```bat
run_game.bat
```

Дальше:

1. `SKIRMISH` → `RULES` → включить **Enable Randomizer**.
2. Задать Seed (или нажать `Generate Seed`), выбрать `Independent`/`Mirrored` и
   нужные пулы. Кнопка `RESET` возвращает всё в обычный режим.
3. Взять Men (или любую сконвертированную фракцию), карту Fords of Isen II, AI-соперника.
4. Старт. Проверяй: в казармах/стрельбищах/конюшнях — юниты других фракций того же
   тира; у крепости есть `Reroll Production`; через ~150 с появляются 3 карты драфта;
   через ~165 с — предупреждение о волне, через 180 с — сама волна; в палантире —
   перемешанные заклинания.

В сети: `MULTIPLAYER` → host → в лобби кнопка `Randomizer…` (настраивает только хост),
гость должен быть на **той же** сборке: протокол v3 сверяет версию Godot и SHA-256
`tiers_db.json`, иначе подключение отклоняется с понятной причиной.

## Если что-то не так

| Симптом | Причина |
|---|---|
| `ContentDB playable: factions=0` | не сконвертированы пакеты или не совпадает `selection.json`; смотри `workspace/…/reports` |
| Фракция в списке «(not converted)» | её пак не собран — конвертируй нужную фракцию |
| `Different game version (needs protocol v3…)` | у второго игрока другая сборка/версия Godot/`tiers_db.json` |
| Кнопка `Native core` недоступна при включённом режиме | так и задумано: в C#-ядре нет CommandSet-слоя |
| `Randomizer: enter a seed…` | Seed пустой или содержит недопустимые символы (нужно 1–32 буквы/цифры) |

## Полный прогон автотестов

```sh
for t in randomizer_core randomizer_production randomizer_draft randomizer_chaos \
         randomizer_persistence randomizer_lobby_network randomizer_lobby_panel \
         randomizer_endurance; do
  godot --headless --path build/openbfme/game --quit-after 120 -s res://tests/${t}_test.gd
done
godot --headless --path build/openbfme/game --quit-after 120 -s res://tests/command_set_upgrade_runtime_runner.gd
```
