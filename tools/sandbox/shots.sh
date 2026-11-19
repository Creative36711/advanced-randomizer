#!/usr/bin/env bash
# Снять скриншоты рандомайзера из собранного дерева игры.
#
#   tools/sandbox/shots.sh /tmp/play              → /tmp/shots
#   tools/sandbox/shots.sh /tmp/play docs/shots   → в свой каталог
#
# Рендер идёт offscreen на Vulkan через SwiftShader (GPU в песочнице нет),
# поэтому --headless НЕ используется: он не рисует кадры вообще.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TREE="${1:?укажите собранное дерево, например /tmp/play}"
OUT="${2:-/tmp/shots}"
WORK="${ARENA_WORK:-/tmp}"
GODOT_DIR="$WORK/godotbin"
GODOT_BIN="$GODOT_DIR/godot"

if [ ! -x "$GODOT_BIN" ]; then
  echo "нет Godot в $GODOT_BIN — сначала tools/sandbox/bootstrap.sh" >&2
  exit 2
fi
if [ ! -f "$TREE/game/project.godot" ]; then
  echo "нет дерева игры: $TREE/game/project.godot" >&2
  exit 2
fi

# Скрипт снимков копируется в дерево: Godot грузит --script по res://-пути.
cp "$HERE/randomizer_shots.gd" "$TREE/game/arena_shots.gd"

LOG=$(mktemp)
VK_ICD_FILENAMES="$GODOT_DIR/vk_swiftshader_icd.json" \
LD_LIBRARY_PATH="$GODOT_DIR:${LD_LIBRARY_PATH:-}" \
"$GODOT_BIN" --path "$TREE/game" --script arena_shots.gd \
  --rendering-driver vulkan --display-driver x11 --resolution 1920x1080 \
  -- "--out=$OUT" >"$LOG" 2>&1 || true

grep -E 'SHOT|GEOM' "$LOG" || true
rm -f "$TREE/game/arena_shots.gd"

# Снимок — это доказательство, поэтому геометрия КАЖДОГО кадра проверяется
# здесь же: попап обязан вмещать панель и стоять внутри лобби, кнопка — не
# вылезать за панель. Раньше оба дефекта проходили незамеченными именно
# потому, что «на глаз» кадр выглядел нормально.
fail=0
grep -q 'GEOM кнопка.*вылезает=true' "$LOG" && { echo "ОШИБКА: кнопка Randomizer вылезает за панель" >&2; fail=1; }
grep -q 'GEOM попап.*вмещает=false' "$LOG" && { echo "ОШИБКА: окно не вмещает панель рандомайзера" >&2; fail=1; }
grep -q 'GEOM попап.*внутри=false' "$LOG" && { echo "ОШИБКА: окно выходит за пределы лобби" >&2; fail=1; }
grep -q 'SHOT_FAIL' "$LOG" && { echo "ОШИБКА: не все кадры сняты" >&2; fail=1; }
rm -f "$LOG"

[ "$fail" = 0 ] && echo "Готово: $OUT" || { echo "Снимки в $OUT, но геометрия не в порядке" >&2; exit 1; }
