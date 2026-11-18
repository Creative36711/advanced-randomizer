# Лаунчер Advanced Randomizer

`AdvancedRandomizer.exe` в корне репозитория — единственное, что нужно нажать
игроку. Он собирается из `launcher/build/Program.cs` в GitHub Actions и
коммитится обратно в корень (`.github/workflows/launcher-release.yml`), потому
что игрок ищет файл в репозитории, а не на странице релизов.

`launcher/start/AdvancedRandomizer.cmd` делает то же самое через `cmd.exe` —
запасной путь, если exe заблокирован политикой.

## Как это устроено

| Файл | Что делает |
|---|---|
| `build/Program.cs` | исходник exe: запускает окно и показывает лог при падении |
| `start/AdvancedRandomizer.cmd` | запасная точка входа через cmd.exe |
| `start/launcher.ps1` | окно (PowerShell 5.1 + WinForms, входит в Windows) |
| `start/engine.py` | все решения: пути, хеши, порядок шагов, отказы |
| `start/pinned.py` | закреплённые адреса и SHA-256 инструментов |
| `start/bootstrap-python.ps1` | ставит Python 3.12.13, на котором работает `engine.py` |
| `start/tests/test_engine.py` | тесты движка (запускаются на любой ОС) |

Окно не принимает решений: оно показывает поля, вызывает `engine.py` и печатает
его вывод. Поэтому всё, что можно сломать (пути, хеши, порядок, отказы),
проверяется тестами без Windows.

## Тесты

```sh
python3 -m unittest discover -s launcher/start/tests -v
```

## Что лаунчер скачивает

Только инструменты, никогда — содержимое игр:

| Что | Размер | Закреплено |
|---|---|---|
| Python 3.12.13 (python-build-standalone) | ≈ 12 МБ | SHA-256 архива и `python.exe` |
| Godot 4.7.2 | 86 МБ | SHA-256 архива |
| Git (MinGit) | ≈ 50 МБ | только если в системе нет `git`; хеш архива **не закреплён** — лаунчер откажется ставить непроверенный файл и назовёт измеренный хеш |
| FFmpeg 8.1.1 | ≈ 80 МБ | архивы переезжают; проверяются сами `ffmpeg.exe`/`ffprobe.exe` по хешам импортёра |
| Blender 4.2.0 + OpenSAGE W3D плагин | ≈ 400 МБ | ставит сам импортёр (`bootstrap-tools`), хеши в upstream |

Если GitHub недоступен (некоторые провайдеры режут релизы), лаунчер пишет,
куда положить скачанный файл вручную: `<папка лаунчера>/downloads/`.

## Где что лежит

По умолчанию `<USERPROFILE>\Advanced Randomizer`, настройки — в
`%APPDATA%\AdvancedRandomizer\settings.json`:

```
<папка лаунчера>/
  openbfme/                 собранное дерево (prepare.py + наш патч и game/)
    game/                   проект Godot
    workspace/content-packs конвертированный приватный контент
    workspace/retail-work   кэш импортёра, окружение Python, инструменты
  tools/                    Python, Godot, MinGit, FFmpeg
  downloads/                скачанные архивы (можно подложить вручную)
  .launcher/                отметки о выполненных шагах
```

Ничего из этого не попадает в git: `.gitignore` игнорирует `build/`, `.cache/`
и `workspace/`.
