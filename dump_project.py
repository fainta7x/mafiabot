import os

OUTPUT_FILE = "project_context.txt"

# Собираем только код
ALLOWED_EXTENSIONS = {'.py', '.env', '.ini'}  # Убрали .txt и .json, чтобы случайно не хапнуть логи/базы данных

# Расширенный список игнорируемых папок
IGNORE_DIRS = {
    'venv', '.venv', 'env', '.env', 'pip-env', 'ANACONDA', # Виртуальные окружения
    '.git', '.idea', '__pycache__', '.pytest_cache',       # Системные папки
    'migrations', 'static', 'media', 'node_modules'        # Крупные ассеты
}
IGNORE_FILES = {OUTPUT_FILE, 'dump_project.py', '.gitignore', 'package-lock.json'}


def build_context():
    project_root = os.path.dirname(os.path.abspath(__file__))
    total_files = 0

    with open(os.path.join(project_root, OUTPUT_FILE), 'w', encoding='utf-8') as out_f:
        out_f.write("================================================================================\n")
        out_f.write(f"CLEAN PROJECT CODEBASE DUMP\n")
        out_f.write("================================================================================\n\n")

        for root, dirs, files in os.walk(project_root):
            # Фильтруем папки на верхнем уровне и в подпапках
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]

            for file in files:
                if file in IGNORE_FILES or file.startswith('.'):
                    continue

                _, ext = os.path.splitext(file)
                if ext.lower() not in ALLOWED_EXTENSIONS:
                    continue

                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, project_root)

                out_f.write(f"\n{'=' * 80}\n")
                out_f.write(f"FILE: {rel_path}\n")
                out_f.write(f"{'=' * 80}\n\n")

                try:
                    with open(full_path, 'r', encoding='utf-8') as in_f:
                        out_f.write(in_f.read())
                    total_files += 1
                except Exception as e:
                    out_f.write(f"[ОШИБКА ЧТЕНИЯ ФАЙЛА: {e}]\n")

                out_f.write("\n")

    print(f"✨ Готово! Успешно обработано чистых файлов с кодом: {total_files}")
    print(f"📂 Новый результат сохранен в: {os.path.join(project_root, OUTPUT_FILE)}")


if __name__ == "__main__":
    build_context()