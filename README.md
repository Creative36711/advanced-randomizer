# Advanced Randomizer

Рандомайзер для **Rise of the Witch-king 2.01** поверх Godot-порта OpenBFME.
Цель — режим, которого не мог дать закрытый движок SAGE.

## Быстрый старт

```bash
tools/sandbox/bootstrap.sh          # окружение: Godot 4.7.2, Blender, медиа (~75 с)
tools/sandbox/build_engine.sh       # сборка движка (долго, см. RUNBOOK)
```

**Новой сессии читать сначала `docs/RUNBOOK.md`** — там всё: где что лежит,
какие дефекты upstream обойдены, как запустить игру, какие файлы нужны.

## Структура

| Путь | Что |
|---|---|
| `upstream/` | снимок `Open-BFME/openbfme-godot` (18.11.2026), GPLv3 |
| `tools/sandbox/` | окружение и сборка одной командой |
| `tools/big_roundtrip.py` | разбор и сборка архивов SAGE `.big` байт-в-байт |
| `docs/RUNBOOK.md` | **как работать: сборка, запуск, файлы игры** |
| `docs/RESEARCH.md` | что Randomizer может дать только на Godot |
| `docs/ART-PIPELINE.md` | правило «SVG или генерация» |
| `docs/SANDBOX.md` | детали песочницы (SwiftShader, bpy, хромакей) |

## Происхождение

Ранняя версия строилась на ветке upstream `bf06a22b` (`legacy-final`,
GDScript-симуляция) и требовала патч 2.02. Это тупик: nightly с ноября работает
на 2.01 **без 2.02**, а симуляция переехала в C++. История удалена, но
осталась в git.

Лицензия upstream — **GPLv3**; наши изменения открыты по той же лицензии.
