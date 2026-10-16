import os
import json

def clean_folder(path):
    # Archivos o carpetas que NO queremos borrar
    exclude = {'noticias_ejecutadas', 'FotosHs'}
    
    for file in os.listdir(path):
        full_path = os.path.join(path, file)
        # Solo borrar archivos que no estén en exclude
        if os.path.isfile(full_path) and file not in exclude:
            os.remove(full_path)
    print(f" Carpeta limpiada: {path}")

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else []

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
