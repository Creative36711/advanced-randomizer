# Точки интеграции (RotWK, до внесения изменений)

В исходном `advanced-randomizer` нет движка. Этот репозиторий — исходный overlay для
[OpenBFME `legacy-final`](https://github.com/Open-BFME/openbfme-godot/tree/bf06a22baab9713ca51cfa03d017534e3b4f752c),
последней версии ветви с GDScript Skirmish. Более новый `main` использует другой движок
(`engine/src/GameLogic`, `GodotGameWorld`, APT HUD) и не является совместимой целью.
`Creative36711/open-bfme/RotWK` содержит файлы розничной игры, а не исходники Godot.

Пути относительно `game/src` собранного дерева:

| Подсистема | Реальный путь и контракт |
|---|---|
| Старт | `ui/skirmish_setup.gd` → `ui/main_menu.gd` → `core/game_state.gd`; для ENet — `ui/multiplayer_lobby.gd`. `retail_slice/retail_vertical_slice.gd` собирает `gameplay_rules`, реестры команд и армии, затем вызывает `RetailSliceSim.setup` **до** первого тика. |
| Данные | `ContentDB` читает сконвертированные документы объектов/фракций. `retail_faction_manifest.gd` и `retail_sim_config.gd` превращают маршруты найма, слоты CommandSet и ObjectDefinitions в `_unit_production_rules`; у экземпляра здания список `production`, у игрока — свой spellbook bundle. |
| Мир и ИИ | `retail_sim_production.gd::queue_unit` проверяет владельца, слот, апгрейды, CP и ресурсы. Затем `_step_production` вызывает `_add_battalion`. `retail_sim_ai.gd::_ai_run_production_window` использует тот же вход очереди. |
| HUD | `retail_vertical_slice.gd::_sync_radial_commands` и `retail_hud.gd` строят панель для выбранного объекта. Действия идут через `_apply_local_command`, **не** меняют мир из UI. |
| Lockstep | `retail_command.gd`, `retail_lockstep_session.gd`, `RetailSliceSim.apply_command`; фиксированный шаг 0,1 с, команды упорядочены по тику, команде игрока и sequence. `retail_sim_persistence.gd` отвечает за снимок и хеш, включая правила. |

## Что добавлено и где

| Слой | Файлы | Точка подключения |
|---|---|---|
| Меню/лобби | `game/src/ui/skirmish_setup.gd`, `main_menu.gd`, `multiplayer_lobby.gd`, `scripts/modes/randomizer/ui/lobby_panel.gd` | RULES в solo, `Randomizer…` в MP; `retail_randomizer` в `GameState`, `randomizer` в `lobby_settings`. |
| Симуляция | `retail_slice/retail_slice_sim.gd`, `retail_sim_{production,construction,powers,persistence}.gd`, `randomizer_match.gd` | экземпляр режима в `setup`, пересчёт цены/скорости, тик режима, книга режима, снапшот. |
| Команды | `retail_command.gd`, `retail_slice_sim.gd` | `ar_draft`, `ar_reroll` — только при включённом режиме. |
| Сеть | `retail_lockstep_session.gd` | PROTOCOL v3, `randomizer` в настройках и echo, сверка отпечатка базы на join. |
| Сеть (сцена) | `retail_vertical_slice.gd` | эффекты метеоров, `retail_randomizer`, `retail_mp_local_team`-совместимое подключение гостя. |

Baseline: официальный Godot 4.7.2, headless import и `command_set_upgrade_runtime_runner.gd`: **18/18**.
Розничных пакетов здесь нет; upstream при старте пишет предупреждение о недостающей заставке и обнаруживает 0 пакетов. Это не тест графического матча с розничными данными.
