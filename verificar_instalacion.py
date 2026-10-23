#!/usr/bin/env python3
"""
Verificador de instalación Nova v3.1 — Limpio
"""
import os
import sys
import json
import urllib.request
import shutil
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
ERRORS = []
WARNINGS = []

def print_header(title):
    print("=" * 60)
    print(f"🔍 {title}")
    print("=" * 60)

def print_ok(msg):
    print(f"✅ {msg}")

def print_err(msg):
    print(f"❌ {msg}")
    ERRORS.append(msg)

def print_warn(msg):
    print(f"⚠️  {msg}")
    WARNINGS.append(msg)

def check_python():
    print_header("ENTORNO PYTHON")
    print(f"ℹ️  Python: {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print_warn("Python 3.10+ recomendado para mejor compatibilidad")
    else:
        print_ok(f"Python {sys.version_info.major}.{sys.version_info.minor} OK")

def check_file(path, desc, required=True):
    full = os.path.join(BASE, path)
    if os.path.exists(full):
        size = os.path.getsize(full)
        if size > 1024 * 1024:
            print_ok(f"{desc} ({path}) — {size / (1024*1024):.1f} MB")
        elif size > 1024:
            print_ok(f"{desc} ({path}) — {size / 1024:.1f} KB")
        else:
            print_ok(f"{desc} ({path}) — {size} B")
        return True
    else:
        if required:
            print_err(f"{desc} NO encontrado: {path}")
        else:
            print_warn(f"{desc} NO encontrado (opcional): {path}")
        return False

def check_dir(path, desc, required=True):
    full = os.path.join(BASE, path)
    if os.path.isdir(full):
        count = sum(1 for _, _, files in os.walk(full) for _ in files)
        print_ok(f"{desc} ({path}) — {count} archivos")
        return True
    else:
        if required:
            print_err(f"{desc} NO encontrado: {path}")
        else:
            print_warn(f"{desc} NO encontrado (opcional): {path}")
        return False

def check_module(module_name, install_cmd, critical=True):
    try:
        __import__(module_name)
        print_ok(f"{module_name} instalado")
        return True
    except ImportError:
        if critical:
            print_err(f"{module_name} no instalado. Ejecuta: {install_cmd}")
        else:
            print_warn(f"{module_name} no instalado (opcional). Ejecuta: {install_cmd}")
        return False

# =============================================================================
# SOLUCIÓN #5: VERIFICAR QUE OLLAMA REALMENTE USA LA GPU
# =============================================================================
# Antes no había forma de saber, sin abrir el Administrador de Tareas, si
# Ollama estaba corriendo los modelos en la GPU o si se había caído a CPU
# (la causa #1 de lentitud en las respuestas de chat). Esta verificación:
#   1) Confirma si hay una GPU NVIDIA visible para el sistema (nvidia-smi).
#   2) Le pregunta directamente a Ollama (endpoint /api/ps) en qué procesador
#      tiene cargado cada modelo AHORA MISMO.
def check_gpu():
    print_header("GPU Y ACELERACIÓN DE OLLAMA")

    gpu_nvidia_detectada = False
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            r = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total,memory.used,driver_version",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0 and r.stdout.strip():
                gpu_nvidia_detectada = True
                for linea in r.stdout.strip().splitlines():
                    print_ok(f"GPU NVIDIA detectada: {linea.strip()}")
            else:
                print_warn("nvidia-smi está pero no devolvió información de GPU")
        except Exception as e:
            print_warn(f"No se pudo consultar nvidia-smi: {e}")
    else:
        print_warn("nvidia-smi no encontrado en PATH — probablemente no hay GPU NVIDIA "
                    "o los drivers no están instalados. Ollama usará CPU (mucho más lento).")

    # Consulta a Ollama qué está corriendo AHORA MISMO y en qué procesador.
    try:
        req = urllib.request.Request("http://localhost:11434/api/ps", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                modelos_activos = data.get("models", [])
                if not modelos_activos:
                    print_warn("Ollama no tiene ningún modelo cargado en este momento "
                               "(normal si Nova no se ha usado todavía).")
                for m in modelos_activos:
                    nombre = m.get("name", m.get("model", "?"))
                    size_vram = m.get("size_vram", 0)
                    size_total = m.get("size", 1) or 1
                    pct_gpu = round((size_vram / size_total) * 100) if size_total else 0
                    if pct_gpu >= 95:
                        print_ok(f"'{nombre}' corriendo 100% en GPU — óptimo")
                    elif pct_gpu > 0:
                        print_warn(f"'{nombre}' corriendo {pct_gpu}% GPU / {100-pct_gpu}% CPU "
                                   f"(modelo grande para tu VRAM disponible, esperá lentitud parcial)")
                    else:
                        print_err(f"'{nombre}' corriendo 100% en CPU — esta es probablemente "
                                  f"tu principal causa de lentitud en las respuestas")
            else:
                print_warn("Ollama respondió con código inesperado al consultar /api/ps")
    except urllib.error.URLError:
        print_warn("No se pudo consultar /api/ps (¿Ollama está corriendo? "
                    "Este chequeo requiere que Nova o Ollama ya hayan cargado un modelo).")
    except Exception as e:
        print_warn(f"No se pudo verificar uso de GPU en Ollama: {e}")

    if not gpu_nvidia_detectada:
        print()
        print_warn("Sin GPU NVIDIA detectada: considera usar modelos más chicos "
                    "(ej. 'moondream' en vez de 'gemma3:4b' para visión) para compensar.")

def check_piper():
    print_header("MODELO DE VOZ PIPER (TTS)")
    check_file("es_AR-daniela-high.onnx", "Modelo Piper .onnx")
    check_file("es_AR-daniela-high.onnx.json", "Config Piper .json", required=False)

    piper_cli = shutil.which("piper") or shutil.which("piper.exe")
    if piper_cli:
        print_ok(f"Piper CLI encontrado: {piper_cli}")
    else:
        print_warn("Piper CLI no encontrado en PATH. Se usará la librería Python si está disponible.")

def check_ollama_models():
    print_header("OLLAMA — MODELOS DE IA")
    models_needed = ["llama3.2:1b", "llava:latest", "moondream:latest"]
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                installed = [m.get("name", m.get("model", "")) for m in data.get("models", [])]
                print_ok(f"Ollama respondiendo. Modelos instalados: {len(installed)}")
                for needed in models_needed:
                    base_name = needed.split(":")[0]
                    found = any(base_name in inst for inst in installed)
                    if found:
                        print_ok(f"Modelo '{needed}' disponible")
                    else:
                        print_warn(f"Modelo '{needed}' NO instalado. Ejecuta: ollama pull {needed}")
            else:
                print_warn("Ollama respondió con código inesperado")
    except urllib.error.URLError:
        print_err("Ollama no detectado en localhost:11434. Asegúrate de que esté corriendo.")
    except Exception as e:
        print_warn(f"No se pudo verificar modelos Ollama: {e}")

def check():
    print_header("VERIFICADOR DE INSTALACIÓN NOVA v3.1")

    check_python()

    print_header("ARCHIVOS DEL PROYECTO 3D")
    check_file("Nova3D/index.html", "Renderizador WebGL")
    check_dir("Nova3D/js", "Librerías JS")
    check_file("Nova3D/js/three.module.js", "Three.js core")
    check_file("Nova3D/js/GLTFLoader.module.js", "GLTFLoader")
    check_file("Nova3D/js/three-vrm.module.js", "Three-VRM")
    check_file("Nova.vrm", "Modelo 3D VRM")
    check_file("nova_3d_controller.py", "Controlador Qt")
    check_file("nova_asistente.py", "Asistente principal")

    print_header("ARCHIVOS DE DATOS")
    check_piper()
    check_dir("vosk-model-small-es-0.42", "Modelo Vosk (STT offline)")
    check_file("perfiles_nova.json", "Perfiles", required=False)
    check_file("nova_memoria.json", "Memoria", required=False)

    print_header("DEPENDENCIAS PYTHON — UI Y RENDERIZADO")
    check_module("PyQt6", "pip install PyQt6 PyQt6-WebEngine")
    try:
        from PyQt6 import QtWebEngineWidgets
        print_ok("PyQt6-WebEngine disponible")
    except ImportError:
        print_err("PyQt6-WebEngine no disponible. Ejecuta: pip install PyQt6-WebEngine")
    check_module("customtkinter", "pip install customtkinter")

    print_header("DEPENDENCIAS PYTHON — AUDIO")
    check_module("pygame", "pip install pygame")
    check_module("pyaudio", "pip install PyAudio", critical=False)
    check_module("sounddevice", "pip install sounddevice", critical=False)
    check_module("soundfile", "pip install soundfile", critical=False)
    check_module("speech_recognition", "pip install SpeechRecognition")
    check_module("vosk", "pip install vosk")
    check_module("numpy", "pip install numpy")
    check_module("noisereduce", "pip install noisereduce", critical=False)

    print_header("DEPENDENCIAS PYTHON — CONTROL Y VISIÓN")
    check_module("pyautogui", "pip install pyautogui")
    check_module("PIL", "pip install Pillow")
    check_module("pynput", "pip install pynput", critical=False)

    print_header("DEPENDENCIAS PYTHON — IA")
    check_module("ollama", "pip install ollama")

    check_ollama_models()
    check_gpu()  # SOLUCIÓN #5

    print_header("UTILIDADES DEL SISTEMA")
    if sys.platform == "win32":
        print_ok("Plataforma: Windows")
    else:
        print_warn("Plataforma no Windows. Algunos comandos (calc, notepad) pueden no funcionar.")

    print("=" * 60)
    if ERRORS:
        print(f"🚨 ERRORES CRÍTICOS ({len(ERRORS)}):")
        for e in ERRORS:
            print(f"   ❌ {e}")
        print()
        print("💡 Corrige los errores antes de ejecutar: python nova_asistente.py")
    else:
        print("🎉 TODO LISTO — Nova puede ejecutarse")
        print("   ▶️  Ejecuta: python nova_asistente.py")

    if WARNINGS:
        print()
        print(f"⚠️  ADVERTENCIAS ({len(WARNINGS)}):")
        for w in WARNINGS:
            print(f"   ⚠️  {w}")

    print("=" * 60)
    return len(ERRORS) == 0

if __name__ == "__main__":
    ok = check()
    sys.exit(0 if ok else 1)