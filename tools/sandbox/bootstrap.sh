#!/usr/bin/env bash
# Поднять окружение для работы над OpenBFME в песочнице Arena одной командой.
#
#   tools/sandbox/bootstrap.sh            # всё нужное: Godot + Blender + медиа
#   tools/sandbox/bootstrap.sh --check    # только проверить, что уже есть
#   tools/sandbox/build_engine.sh         # отдельно: собрать движок (долго)
#
# Песочница сбрасывается между сессиями: /tmp обнуляется. Поэтому всё, что
# ставится, ставится повторно этим скриптом, а не считается «уже стоящим».
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WORK="${WORK:-/tmp}"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

say()  { printf '==> %s\n' "$*"; }
ok()   { printf '    ✓ %s\n' "$*"; }
miss() { printf '    ✗ %s\n' "$*"; }

# ---------------------------------------------------------------- зависимости
install_toolchain() {
  if /tmp/buildenv/bin/cmake --version >/dev/null 2>&1 && /tmp/buildenv/bin/ninja --version >/dev/null 2>&1; then
    ok "cmake/ninja уже есть: $(/tmp/buildenv/bin/cmake --version | head -1)"
    return
  fi
  [ "$CHECK" = 1 ] && { miss "нет cmake/ninja в /tmp/buildenv"; return; }
  say "cmake + ninja (в /tmp/buildenv; apt без root недоступен)"
  python3 -m venv /tmp/buildenv
  /tmp/buildenv/bin/pip -q install --disable-pip-version-check cmake ninja
  ok "$(/tmp/buildenv/bin/cmake --version | head -1), ninja $(/tmp/buildenv/bin/ninja --version)"
}

# ---------------------------------------------------------------- Godot 4.7.2
# Источник — САМ РЕПОЗИТОРИЙ: tools/vendor/godot/. Три файла (две xz-части
# бинарника и SwiftShader) плюс SHA256SUMS и VERSION лежат в git, поэтому сборка
# не зависит ни от сети, ни от другого репозитория. Части склеиваются и
# сверяются по хешу — см. install_godot ниже.
#
# Раньше здесь был Creative36711/synapse: это был просто склад готовых бинарников,
# к движку OpenBFME он отношения не имеет. Файлы забраны оттуда ОДИН раз и
# подписаны теми же sha256, что лежали в его SHA256SUMS.
GODOT_DIR="$WORK/godotbin"
GODOT_BIN="$GODOT_DIR/godot"
GODOT_VENDOR="$REPO/tools/vendor/godot"
install_godot() {
  if [ -x "$GODOT_BIN" ]; then ok "Godot уже есть: $($GODOT_BIN --version 2>/dev/null | tail -1)"; return; fi
  [ "$CHECK" = 1 ] && { miss "Godot нет ($GODOT_BIN)"; return; }
  mkdir -p "$GODOT_DIR"
  say "Godot 4.7.2 + SwiftShader из tools/vendor/godot (~66 МБ)"
  [ -f "$GODOT_VENDOR/SHA256SUMS" ] || { miss "нет $GODOT_VENDOR/SHA256SUMS (клон неполный?)"; return; }
  cp "$GODOT_VENDOR/SHA256SUMS" "$GODOT_DIR/SHA256SUMS"
  cp "$GODOT_VENDOR/swiftshader-linux-x86_64.tar.xz" "$GODOT_DIR/" || return
  local part
  for part in 00 01; do
    cp "$GODOT_VENDOR/godot-linux-x86_64.xz.part-$part" "$GODOT_DIR/part-$part.xz" || return
    printf '    взят кусок %s из репозитория\n' "$part"
  done
  # SHA256SUMS подписывает три вещи: две части, склеенный .xz и распакованный
  # бинарник. Имена в файле не совпадают с нашими — сверяем по хешу.
  python3 - "$GODOT_DIR" <<'PYEOF'
import hashlib, sys, os
d = sys.argv[1]
want = {}
for line in open(os.path.join(d, "SHA256SUMS"), encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    h, _, name = line.partition("  ")
    want[name.strip()] = h
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
for name, part in (("godot-linux-x86_64.xz.part-00", "part-00.xz"),
                   ("godot-linux-x86_64.xz.part-01", "part-01.xz")):
    got = sha(os.path.join(d, part))
    if got != want.get(name):
        sys.exit(f"часть {part}: {got} != {want.get(name)}")
print("    части сходятся")
PYEOF
  [ $? -ne 0 ] && { miss "части не сошлись"; return; }
  ( cd "$GODOT_DIR" && cat part-00.xz part-01.xz > godot.xz ) || return
  # SHA256SUMS не содержит хеша склейки — сверяем только части (выше) и
  # РАСПАКОВАННЫЙ бинарник (ниже), это и есть настоящая проверка содержимого.
  ( cd "$GODOT_DIR" && xz -d -f godot.xz ) || return
  python3 - "$GODOT_DIR" <<'PYEOF'
import hashlib, sys, os
d = sys.argv[1]
want = {}
for line in open(os.path.join(d, "SHA256SUMS"), encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    h, _, name = line.partition("  ")
    want[name.strip()] = h
h = hashlib.sha256()
with open(os.path.join(d, "godot"), "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
exp = want.get("godot (uncompressed)")
if h.hexdigest() != exp:
    sys.exit(f"бинарник: {h.hexdigest()} != {exp}")
print("    бинарник сходится")
PYEOF
  [ $? -ne 0 ] && { miss "бинарник не сошёлся"; return; }
  mv "$GODOT_DIR/godot" "$GODOT_BIN" 2>/dev/null || true
  chmod +x "$GODOT_BIN" 2>/dev/null
  ok "Godot: $($GODOT_BIN --version 2>/dev/null | tail -1)"
}

# Запуск Godot с SwiftShader (GPU в песочнице нет; --headless кадров не рисует)
godot_run() {
  VK_ICD_FILENAMES="$GODOT_DIR/vk_swiftshader_icd.json" \
  LD_LIBRARY_PATH="$GODOT_DIR:${LD_LIBRARY_PATH:-}" \
  "$GODOT_BIN" "$@"
}

# ------------------------------------------------------------- Blender (bpy)
# БЛЕНДЕР 5.0.1 — ЕДИНСТВЕННАЯ ВЕРСИЯ ЭТОГО ПРОЕКТА. Не «по умолчанию», а
# закреплённая: колесо проверяется по SHA-256, и подмена версии не проскочит.
#
# Почему именно 5.0.1:
#   - это последняя версия, собранная под CPython 3.11, а 3.11 — единственный
#     Python в песочнице (3.13 взять неоткуда: python.org и GitHub Releases
#     заблокированы, проверил uv и pbs-installer);
#   - все три реальные модели vault (coin, rocket, safe) проходят на ней
#     без потерь: GLB совпадает байт в байт с любым другим Blender;
#   - стабы X11 подходят к ней как есть.
#
# ЧЕГО ОНА НЕ ДАЁТ: рендера. Ни Workbench, ни Cycles — оба требуют libEGL.so.1,
# которой в песочнице нет и взять неоткуда (docs/BLENDER.md). Модели и анимации
# делаются, картинки рендерит Godot (tools/vendor/godot, SwiftShader).
BPY_VERSION="5.0.1"
# SHA-256 manylinux-колеса bpy 5.0.1 (cp311, manylinux_2_28_x86_64), 374 257 847 Б.
# PyPI отдаст другое колесо — установка остановится, подмена не проскочит.
BPY_WHEEL_SHA256="79c6e421f53ea24a5961d86eefb8141798eee708682415eb4f5a952c2abdeb8b"
install_bpy() {
  local venv="$WORK/bpyenv" stubs="$WORK/bpystubs"
  if [ -x "$venv/bin/python" ] && [ -f "$stubs/USE" ] \
     && LD_LIBRARY_PATH="$stubs" "$venv/bin/python" -c 'import bpy' 2>/dev/null; then
    ok "Blender уже есть: $(LD_LIBRARY_PATH="$stubs" "$venv/bin/python" -c 'import bpy; print(bpy.app.version_string)')"; return
  fi
  [ "$CHECK" = 1 ] && { miss "нет bpy в $venv"; return; }
  command -v python3.11 >/dev/null || { miss "нужен python3.11 (bpy 5.x собран только под cp311)"; return; }
  say "Blender $BPY_VERSION как модуль bpy (~355 МБ, один раз)"
  python3.11 -m venv "$venv"
  # закрепление по хешу: скачиваем колесо сами, сверяем и ставим файлом
  local whl="$WORK/bpy-$BPY_VERSION.whl"
  if ! "$venv/bin/pip" -q download --disable-pip-version-check --no-deps -d "$WORK/bpywheel" "bpy==$BPY_VERSION" 2>/dev/null; then
    miss "не скачалось колесо bpy==$BPY_VERSION"; return
  fi
  whl=$(ls "$WORK"/bpywheel/bpy-"$BPY_VERSION"-*.whl 2>/dev/null | head -1)
  [ -f "$whl" ] || { miss "колесо bpy==$BPY_VERSION не найдено после скачивания"; return; }
  local got
  got=$(python3 -c "import hashlib,sys; h=hashlib.sha256(); f=open(sys.argv[1],'rb'); [h.update(c) for c in iter(lambda: f.read(1<<20), b'')]; print(h.hexdigest())" "$whl")
  if [ "$got" != "$BPY_WHEEL_SHA256" ]; then
    miss "колесо bpy==$BPY_VERSION подменено: $got != $BPY_WHEEL_SHA256"; return
  fi
  ok "колесо сверено по SHA-256"
  # ставим файлом (он проверен), зависимости — обычным путём с индекса
  "$venv/bin/pip" -q install --disable-pip-version-check "$whl"
  local pkg
  pkg=$(ls -d "$venv"/lib/python*/site-packages/bpy | head -1)
  mkdir -p "$stubs"
  python3.11 "$HERE/bpy_stubs.py" "$pkg" "$stubs" >/dev/null
  ok "bpy готов; запуск: LD_LIBRARY_PATH=$stubs $venv/bin/python"
}

# ---------------------------------------------------------------- Медиа (Pillow)
install_media() {
  local venv="$WORK/mediaenv"
  if [ -x "$venv/bin/python" ] && "$venv/bin/python" -c 'import PIL' 2>/dev/null; then
    ok "медиа-окружение уже есть: $venv"; return
  fi
  [ "$CHECK" = 1 ] && { miss "нет медиа-окружения: $venv"; return; }
  say "Медиа-окружение (хромакей)"
  python3 -m venv "$venv"
  "$venv/bin/pip" -q install --disable-pip-version-check Pillow numpy
  ok "готово"
}

install_toolchain
install_godot
install_media
install_bpy

cat <<EOF

Готово. Дальше:
  движок:    tools/sandbox/build_engine.sh          # сборка (15+ мин, 2 ядра)
  проверка:  tools/sandbox/build_engine.sh --check  # что уже собрано
  Godot:     $GODOT_BIN --version
  хромакей:  $WORK/mediaenv/bin/python $HERE/cutout_chromakey.py in.png out.png --crop

Переменные для запуска игры (см. docs/RUNBOOK.md):
  export ROTWK_INSTALL=/path/to/RotWK
  export BFME2_INSTALL=/path/to/BFME2
  godot_run --path upstream/godot
EOF
