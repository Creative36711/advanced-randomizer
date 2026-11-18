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
Для игры — принадлежащие вам BFME2 1.06, RotWK 2.01 + Patch 2.02 v9.7.7 и
сконвертированные карты/фракции: см. `build/openbfme/README.md` и импортёр в этом
же дереве. Собирайте и запускайте **из этого дерева**, а не из незатронутого upstream.
[Инспекция и точки интеграции](docs/integration.md).
