from pathlib import Path


def inicial_start_promt():
    # Задаём корневой путь проекта.
    file_path = str(Path(__file__).resolve().parents[0]) + '/promt.txt'
    # Чтение файла с промтом
    with open(file_path, 'r') as file:
        return file.read()