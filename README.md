# Advanced Randomizer · OpenBFME

Исходный мод для **RotWK / GDScript Skirmish** на Godot 4.7.2. Движок закреплён
по SHA в `tools/prepare.py`, розничные ресурсы не распространяются. Это не мод для
C++-версии `openbfme-godot/main` или оригинального `game.dat`.

```sh
python3 tools/prepare.py
godot --headless --path build/openbfme/game --editor --import
godot --headless --path build/openbfme/game --script res://tests/command_set_upgrade_runtime_runner.gd
```

Нужны Python 3.9+, Git и Godot 4.7.2.
Пошаговая инструкция для игрока (сборка → конвертация своих файлов → запуск режима):
**[docs/RUNNING.md](docs/RUNNING.md)**.
Для игры — принадлежащие вам BFME2 1.06, RotWK 2.01 + Patch 2.02 v9.7.7 и
сконвертированные карты/фракции: см. `build/openbfme/README.md` и импортёр в этом
же дереве. Собирайте и запускайте **из этого дерева**, а не из незатронутого upstream.
[Инспекция и точки интеграции](docs/integration.md).

## Режим Advanced Randomizer

Матч включается через RULES в одиночной схватке или кнопку `Randomizer…` в сетевом
лобби. Seed — 1–32 буквы/цифры (кнопка генерирует криптостойкий код); `Independent`
даёт каждому игроку свой сбалансированный набор, `Mirrored` — общий. Включение режима
принудительно выбирает `Retail slice` и отключает `Native core` (в нём нет CommandSet-слоя).

| Модуль | Что делает |
|---|---|
| `randomizer_config.gd`, `seeded_rng.gd`, `tier_registry.gd` | Конфиг, SHA-256-seed → PCG RNG, 96 записей `data/tiers_db.json` (7 фракций, тиры 1–4, теги). |
| `command_set_shuffler.gd` | До первого тика заменяет слоты найма/героев равного тира; цена и время берутся у исходного юнита; платный `Reroll Production` только для этого здания. ИИ ходит через тот же `queue_unit`. |
| `spellbook_shuffler.gd` | Меняет прессы палантира равного тира, сохраняя науки и цены; книга принадлежит режиму. |
| `draft_manager.gd` + `ui/match_hud.gd` | За 3 карты каждые 150 с и после завершения крепости/её апгрейда; 30 с авто-выбора, без паузы; спавн отряда/героя, заклинание, бафф тега. |
| `chaos_event_system.gd` + `ui/meteor_fx.gd` | Общая волна каждые 180 с с баннером за 15 с; 5 мутаторов, включая предательство отряда и метеоры. |
| `ui/lobby_panel.gd` | Панель настроек; в сети — host-authoritative, включается в `lobby.settings` и в echo запуска. |

Детерминизм: один `SeededRNG` на матч, режимные команды `ar_draft`/`ar_reroll` идут через
lockstep, режимное состояние входит в снапшот/хеш. Сетевой протокол поднят до v3 и при
подключении сверяет версию Godot и SHA-256 `tiers_db.json`; ванильный клиент не пройдёт.
Звук предупреждения — `audio/horn-1.ogg` из Battle for Wesnoth (GPL-2.0+, см. `licenses/audio.md`).

Проверки (после сборки тем же `prepare.py`):

```sh
for t in randomizer_core randomizer_production randomizer_draft randomizer_chaos \
         randomizer_persistence randomizer_lobby_network randomizer_lobby_panel \
         randomizer_endurance; do
  godot --headless --path build/openbfme/game --quit-after 120 -s res://tests/${t}_test.gd
done
godot --headless --path build/openbfme/game --quit-after 120 -s res://tests/command_set_upgrade_runtime_runner.gd
```
