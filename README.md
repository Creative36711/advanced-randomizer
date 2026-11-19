# Advanced Randomizer

Исследовательский проект: **что позволяет Godot-порт OpenBFME, чего не мог
закрытый движок SAGE.**

## Отправная точка

RotWK 2.01 запускается на OpenBFME nightly **без всяких патчей 2.02**. Мод для
него — это данные (`-mod` / `--mod-install`) или, если он меняет программу,
профиль `--mod-engine`. Правила: `docs/MODS.md`, `docs/MOD-COMPAT.md` в
репозитории Open-BFME/openbfme-godot.

Прежняя попытка строилась на устаревшей ветке `bf06a22b` (`legacy-final`,
GDScript-симуляция), где требовался 2.02. Она удалена; история в git.

## Что в репозитории

| Путь | Что это |
|---|---|
| `docs/ART-PIPELINE.md` | правило «SVG или генерация» |
| `docs/SANDBOX.md` | как поднять окружение (Godot, Blender, хромакей) |
| `tools/sandbox/bootstrap.sh` | одна команда: Godot 4.7.2 + bpy + медиа |
| `tools/sandbox/cutout_chromakey.py` | вырезание фона по хромакею |
| `tools/sandbox/bpy_stubs.py` | стабы X11/GL, чтобы bpy жил без GPU |

## Окружение

```bash
tools/sandbox/bootstrap.sh          # поставить всё
tools/sandbox/bootstrap.sh --check  # проверить
```
