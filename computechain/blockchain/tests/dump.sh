#!/usr/bin/env bash
set -euo pipefail

# Имя выходного файла
OUT_FILE="project_dump.txt"

# Очистить/создать файл дампа
: > "$OUT_FILE"

########################################
# 1. Дерево файлов
########################################

echo "===== FILE TREE =====" >> "$OUT_FILE"
echo >> "$OUT_FILE"

if command -v tree >/dev/null 2>&1; then
    # Полное дерево, включая скрытые файлы, без __pycache__
    tree -a . \
        -I '__pycache__' \
        >> "$OUT_FILE"
else
    # Fallback, если tree не установлен
    find . -mindepth 1 \
        ! -path '*/__pycache__/*' \
        | sed 's|^\./||' | sort >> "$OUT_FILE"
fi

echo >> "$OUT_FILE"
echo "===== FILE CONTENTS =====" >> "$OUT_FILE"
echo >> "$OUT_FILE"

########################################
# 2. Список файлов (кроме __pycache__ и .pyc)
########################################

mapfile -t FILES < <(
    find . -type f \
        ! -name "$(basename "$OUT_FILE")" \
        ! -name 'dump.sh' \
        ! -path '*/__pycache__/*' \
        ! -name '*.pyc' \
        | sort
)

########################################
# 3. Дамп содержимого файлов
########################################

for f in "${FILES[@]}"; do
    rel="${f#./}"  # относительный путь без ./ в начале
    {
        echo "===== $rel ====="
        cat "$f"
        echo
        echo
    } >> "$OUT_FILE"
done
