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
# download.blender.org недоступен, но bpy==4.5.3 есть на pypi: целый Blender
# как модуль. Колесо требует CPython 3.11 и линкуется с X11/GL — стабы закрывают.
BPY_VERSION="${BPY_VERSION:-4.5.3}"
install_bpy() {
  local venv="$WORK/bpyenv" stubs="$WORK/bpystubs"
  if [ -x "$venv/bin/python" ] && [ -f "$stubs/USE" ] \
     && LD_LIBRARY_PATH="$stubs" "$venv/bin/python" -c 'import bpy' 2>/dev/null; then
    ok "Blender уже есть: $(LD_LIBRARY_PATH="$stubs" "$venv/bin/python" -c 'import bpy; print(bpy.app.version_string)')"; return
  fi
  [ "$CHECK" = 1 ] && { miss "нет bpy в $venv"; return; }
  command -v python3.11 >/dev/null || { miss "нужен python3.11 (bpy 4.5.x только под cp311)"; return; }
  say "Blender $BPY_VERSION как модуль bpy (~355 МБ, один раз)"
  python3.11 -m venv "$venv"
  "$venv/bin/pip" -q install --disable-pip-version-check "bpy==$BPY_VERSION"
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
