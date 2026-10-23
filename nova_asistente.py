import customtkinter as ctk
import ollama
import inspect
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import json
import shutil
import wave
import hashlib
import unicodedata
from typing import Dict, Optional
import pygame
import pyautogui
import speech_recognition as sr
from PIL import Image, ImageGrab
import logging

# ==========================
# LOGGING
# ==========================
# Reemplaza el antipatrón "except Exception: pass" / "print(error)" repartido
# por todo el archivo. Las excepciones capturadas se registran con
# logger.exception(), que guarda el traceback completo en nova_asistente.log
# sin interrumpir la ejecución del programa (sistema async/multihilo).
# Se configura ANTES de redirigir sys.stderr a DevNull, y el handler de
# consola usa sys.stdout explícitamente para no perderse en ese filtro.
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "nova_asistente.log")

logger = logging.getLogger("nova_asistente")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)

    _file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(module)s:%(lineno)d | %(message)s"
    ))

    _console_handler = logging.StreamHandler(stream=sys.stdout)
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    logger.addHandler(_file_handler)
    logger.addHandler(_console_handler)
    logger.propagate = False

# 1. Silenciar a nivel de sistema operativo para que el ruido no llegue a la consola
# Esto redirige las advertencias a un flujo nulo (nada se imprimirá)
class DevNull:
    def write(self, msg): pass
    def flush(self): pass

# Redirigir stderr para filtrar el ruido específicamente de PyTorch
sys.stderr = DevNull()

# 2. Mantener las advertencias visibles en otros casos si lo deseas (opcional)
# Si necesitas ver errores reales, esta parte se vuelve más compleja, 
# pero con esto limpiarás el 100% del ruido de 'pin_memory'.


# ==========================
# FIX PATH — arranque automático / Task Scheduler
# ==========================
# Cuando corrés Nova a mano desde una terminal con el venv activado
# (Activate.ps1), esa activación agrega ...\.venv\Scripts al PATH del
# proceso — ahí vive piper.exe, y también los DLLs que la librería de
# Piper necesita en tiempo de ejecución (fonemización vía espeak-ng).
# La tarea programada de Windows (setup_autoarranque.ps1) lanza
# pythonw.exe DIRECTO, sin pasar por esa activación: ese PATH nunca se
# agrega, shutil.which("piper") devuelve None, y la síntesis por
# librería sale con un WAV vacío porque no encuentra sus propios DLLs.
# Lo arreglamos agregando esa carpeta al PATH del proceso nosotros
# mismos, apenas arranca el script — no importa cómo lo hayan lanzado.
_VENV_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts")
if os.path.isdir(_VENV_SCRIPTS_DIR) and _VENV_SCRIPTS_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _VENV_SCRIPTS_DIR + os.pathsep + os.environ.get("PATH", "")

# ==========================
# FIX PATH — DLLs de CUDA para faster-whisper (ctranslate2) en GPU
# ==========================
# torch.cuda.is_available() puede devolver True (trae su propio runtime CUDA
# embebido) aunque falten las DLLs de cuBLAS/cuDNN que ctranslate2 (el motor
# real detrás de faster-whisper) necesita para correr en GPU de verdad. Sin
# esto, cada arranque terminaba viendo "Library cublas64_12.dll is not found"
# y recargando el modelo en CPU — mucho más lento de lo que tu RTX 3050 podría
# dar. En vez de instalar el CUDA Toolkit completo del sistema (pesado, puede
# pedir reinicio), usamos los paquetes pip nvidia-cublas-cu12 / nvidia-cudnn-
# cu12 (instalá con: pip install nvidia-cublas-cu12 nvidia-cudnn-cu12) — traen
# las DLLs solas, viven dentro del venv, y acá las sumamos al PATH del
# proceso, mismo criterio que ya usamos arriba con .venv\Scripts para piper.
try:
    import nvidia.cublas as _cublas_pkg
    import nvidia.cudnn as _cudnn_pkg
    for _pkg in (_cublas_pkg, _cudnn_pkg):
        _carpeta_dll = os.path.join(os.path.dirname(_pkg.__file__), "bin")
        if os.path.isdir(_carpeta_dll) and _carpeta_dll not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _carpeta_dll + os.pathsep + os.environ.get("PATH", "")
except Exception as e:
    logger.debug(
        f"[NOVA] DLLs de CUDA (nvidia-cublas-cu12/nvidia-cudnn-cu12) no disponibles "
        f"({e}) — faster-whisper va a caer a CPU como hasta ahora, sin romper nada."
    )


# ==========================
# MENTE CORE (Cerebro Consciente)
# ==========================
try:
    from nova_mente_core import NovaMenteAdapter, debug_mente
    MENTE_CORE_AVAILABLE = True
except ImportError as e:
    MENTE_CORE_AVAILABLE = False
    logger.debug(f"[NOVA] Mente Core no disponible: {e}")

# ==========================
# NOVA SKILLS (Manos / Capa Motora)
# ==========================
# Habilidades fundamentales (mouse, teclado, ventanas, archivos, sistema...).
# nova_mente_core.py también la importa y la conecta como actuador "skill"
# para las tareas que decide ejecutar por su cuenta; acá se usa además para
# los "reflejos mecánicos" que ejecutar_comandos() resuelve directo, sin
# pasar por el cerebro (ver el helper self._skill() más abajo).
try:
    from nova_skills import SkillRegistry, SKILLS
    NOVA_SKILLS_AVAILABLE = True
except ImportError as e:
    NOVA_SKILLS_AVAILABLE = False
    SkillRegistry = None
    SKILLS = {}
    logger.debug(f"[NOVA] Nova Skills no disponible: {e}")

# ==========================
# PYPDF (lectura de texto de PDFs adjuntos en el chat 3D)
# ==========================
try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError as e:
    PYPDF_AVAILABLE = False
    PdfReader = None
    logger.debug(f"[NOVA] pypdf no disponible: {e}")

# ==========================
# REQUESTS (para resolver el primer video de una búsqueda en YouTube y
# reproducirlo directo, en vez de solo abrir la página de resultados).
# ==========================
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError as e:
    REQUESTS_AVAILABLE = False
    logger.debug(f"[NOVA] requests no disponible ({e})")

# ==========================
# NOVA 3D
# ==========================
NOVA3D_AVAILABLE = False
try:
    from nova_3d_controller import Nova3D
    NOVA3D_AVAILABLE = True
except ImportError as e:
    logger.debug(f"[NOVA] Nova 3D no disponible: {e}")

# ==========================
# NOVA VISION (Ojo / Percepción visual continua)
# ==========================
# FIX: este import no existía en el archivo. Sin él, NovaApp nunca tenía un
# atributo 'vision', así que NovaMenteAdapter.iniciar() (en nova_mente_core.py)
# jamás llamaba a mente.conectar_vision(...) -- su condición es exactamente
# 'hasattr(self.nova, "vision") and self.nova.vision'. Eso dejaba self.predictor
# en None para siempre y, en cadena, las tablas contextos_escritorio y
# estados_usuario nunca se llenaban aunque el código para escribirlas
# funcionara perfectamente.
try:
    from nova_vision import NovaVision
    NOVA_VISION_AVAILABLE = True
except ImportError as e:
    NOVA_VISION_AVAILABLE = False
    logger.debug(f"[NOVA] Nova Vision no disponible: {e}")

# ==========================
# HOTKEY GLOBAL
# ==========================
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

# ==========================
# CONFIGURACIÓN TTS / STT
# ==========================
PIPER_MODEL = "es_AR-daniela-high.onnx"
PIPER_CONFIG = "es_AR-daniela-high.onnx.json"
VOSK_AVAILABLE = False
PiperVoiceClass = None


def _try_import_piper():
    global PiperVoiceClass
    for stmt in ["from piper import PiperVoice", "from piper.voice import PiperVoice"]:
        try:
            exec(f"{stmt}; PiperVoiceClass = PiperVoice", globals())
            return
        except Exception as e:
            logger.debug(f"Estrategia de import de Piper falló: {e}")
    try:
        import piper
        if hasattr(piper, 'PiperVoice'):
            PiperVoiceClass = piper.PiperVoice
        elif hasattr(piper, 'voice') and hasattr(piper.voice, 'PiperVoice'):
            PiperVoiceClass = piper.voice.PiperVoice
    except Exception as e:
        logger.debug(f"piper no disponible: {e}")


_try_import_piper()

try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False

VOSK_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk-model-small-es-0.42")

WHISPER_AVAILABLE = False
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    logger.debug("Import opcional no disponible (ImportError) en <module>")
WHISPER_MODEL_SIZE = "small"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE_TYPE = "float16"

try:
    import pyaudio
    import numpy as np
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    np = None

try:
    import sounddevice as sd
    import soundfile as sf
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False

try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    WINSOUND_AVAILABLE = False
    


class AudioEngine:
    def __init__(self, app):
        self.app = app
        self._cola = queue.Queue()
        self._mutex = threading.Lock()
        self._hablando = False
        self._mute = False
        self._fade_in_ms = 60
        self._fade_out_ms = 200
        self._target_rms = 0.25
        self._hilo_reproduccion = threading.Thread(target=self._bucle_reproduccion, daemon=True)
        self._hilo_reproduccion.start()
        self._temporales = set()
        self._canal_pygame = None
        self._tts_lock = threading.Lock()
        print("[AUDIO] Motor de audio profesional iniciado")

    @property
    def hablando(self):
        with self._mutex:
            return self._hablando

    @property
    def mute(self):
        with self._mutex:
            return self._mute

    def toggle_mute(self):
        with self._mutex:
            self._mute = not self._mute
            if self._mute:
                self._detener_inmediato()
            return self._mute

    def _detener_inmediato(self):
        try:
            if SOUNDDEVICE_AVAILABLE:
                sd.stop()
        except Exception:
            logger.exception("Excepcion silenciada en _detener_inmediato")
        try:
            if pygame.mixer.get_init():
                pygame.mixer.stop()
                pygame.mixer.music.stop()
        except Exception:
            logger.exception("Excepcion silenciada en _detener_inmediato")
        self._hablando = False

    def encolar(self, wav_path, on_start=None, on_end=None):
        if self._mute:
            return False
        self._cola.put({"path": wav_path, "on_start": on_start, "on_end": on_end})
        return True

    def _bucle_reproduccion(self):
        while True:
            try:
                item = self._cola.get(timeout=0.5)
            except queue.Empty:
                continue

            wav_path = item["path"]
            on_start = item.get("on_start")
            on_end = item.get("on_end")

            with self._mutex:
                self._hablando = True

            if on_start:
                try:
                    on_start()
                except Exception:
                    logger.exception("Excepcion silenciada en _bucle_reproduccion")

            try:
                self._reproducir_wav_profesional(wav_path)
            except Exception as e:
                logger.exception(f"[AUDIO] Error reproducción: {e}")
            finally:
                if wav_path in self._temporales:
                    try:
                        os.remove(wav_path)
                        self._temporales.discard(wav_path)
                    except Exception:
                        logger.exception("Excepcion silenciada en _bucle_reproduccion")

                with self._mutex:
                    self._hablando = False

                if on_end:
                    try:
                        on_end()
                    except Exception:
                        logger.exception("Excepcion silenciada en _bucle_reproduccion")

    def _normalizar_rms(self, audio_float, target_rms=0.25):
        if len(audio_float) == 0:
            return audio_float
        rms = np.sqrt(np.mean(audio_float ** 2))
        if rms < 1e-9:
            return audio_float
        gain = min(target_rms / rms, 10.0)
        return np.clip(audio_float * gain, -1.0, 1.0)

    def _aplicar_fade_avanzado(self, audio_float, samplerate, fade_in_ms=60, fade_out_ms=200):
        if len(audio_float) == 0:
            return audio_float

        fade_in_samples = int(samplerate * fade_in_ms / 1000)
        fade_out_samples = int(samplerate * fade_out_ms / 1000)

        if fade_in_samples > 0 and len(audio_float) > fade_in_samples:
            fade_in = np.linspace(0, 1, fade_in_samples)
            fade_in = fade_in ** 2
            audio_float[:fade_in_samples] *= fade_in

        if fade_out_samples > 0 and len(audio_float) > fade_out_samples:
            fade_out = np.linspace(1, 0, fade_out_samples)
            fade_out = fade_out ** 2
            audio_float[-fade_out_samples:] *= fade_out

        return audio_float

    def _reproducir_wav_profesional(self, wav_path):
        if not os.path.exists(wav_path):
            raise FileNotFoundError(f"No existe: {wav_path}")

        if SOUNDDEVICE_AVAILABLE and np is not None:
            try:
                data, samplerate = sf.read(wav_path, dtype='float32')
                if len(data.shape) > 1:
                    data = np.mean(data, axis=1)

                data = self._normalizar_rms(data, self._target_rms)
                data = self._aplicar_fade_avanzado(data, samplerate, self._fade_in_ms, self._fade_out_ms)

                sd.play(data, samplerate)
                duracion = len(data) / samplerate
                t0 = time.time()
                while time.time() - t0 < duracion and not self.app.closing:
                    if self._mute:
                        sd.stop()
                        return
                    time.sleep(0.03)
                sd.stop()
                return
            except Exception as e:
                logger.exception(f"[AUDIO] sounddevice falló: {e}")

        try:
            if pygame.mixer.get_init():
                sound = pygame.mixer.Sound(wav_path)
                sound.set_volume(0.9)
                channel = sound.play()
                if channel:
                    duracion = sound.get_length()
                    t0 = time.time()
                    while channel.get_busy() and not self.app.closing:
                        if self._mute:
                            channel.fadeout(100)
                            return
                        if time.time() - t0 > duracion + 2:
                            break
                        time.sleep(0.03)
                    if channel.get_busy():
                        channel.fadeout(self._fade_out_ms)
                        time.sleep(self._fade_out_ms / 1000.0 + 0.05)
                    channel.stop()
                sound.stop()
                return
        except Exception as e:
            logger.exception(f"[AUDIO] pygame falló: {e}")

        if WINSOUND_AVAILABLE:
            try:
                winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
                return
            except Exception as e:
                logger.exception(f"[AUDIO] winsound falló: {e}")

        raise RuntimeError("Ningún backend de audio disponible")

    def fade_out_global(self, duracion_ms=300):
        try:
            if SOUNDDEVICE_AVAILABLE:
                sd.stop()
        except Exception:
            logger.exception("Excepcion silenciada en fade_out_global")
        try:
            if pygame.mixer.get_init():
                pygame.mixer.fadeout(duracion_ms)
        except Exception:
            logger.exception("Excepcion silenciada en fade_out_global")
        with self._mutex:
            self._hablando = False

    def limpiar_temporales(self):
        for path in list(self._temporales):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                logger.exception("Excepcion silenciada en limpiar_temporales")
        self._temporales.clear()

    def registrar_temporal(self, path):
        self._temporales.add(path)


# =============================================================================
# NOVA APP (ANFITRIÓN DEL BUCLE CERRADO)
# =============================================================================
class NovaApp(ctk.CTk):
    def report_callback_exception(self, exc, val, tb):
        """FIX: Tkinter manda las excepciones de CUALQUIER callback programado
        con self.after(...) (como saludo_inicial, procesar_cola, etc.) a
        sys.stderr — que más arriba redirigimos a DevNull para silenciar el
        ruido de PyTorch. Sin este override, un error real ahí adentro
        desaparecía sin dejar rastro: ni en consola, ni en el log. Ahora se
        loguea de verdad (con traceback completo) en vez de perderse."""
        logger.error("[NOVA] Excepción no capturada en callback de Tkinter", exc_info=(exc, val, tb))

    def __init__(self):
        super().__init__()

        self._t0_arranque = time.time()
        logger.info("[ARRANQUE] NovaApp.__init__ comienza")

        self.title("Nova")
        self.geometry("1x1+9999+9999")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#000000")
        self.attributes("-transparentcolor", "#000000")
        self.withdraw()

        self.base_dir = os.path.dirname(os.path.abspath(__file__))

        self.nova3d = None
        if NOVA3D_AVAILABLE:
            try:
                self.nova3d = Nova3D(self.base_dir, width=380, height=480, x=100, y=100)
                self.nova3d.start()
                print("[NOVA] Cuerpo 3D iniciando...")
                logger.info(f"[ARRANQUE] Nova3D.start() lanzado ({time.time() - self._t0_arranque:.1f}s)")
            except Exception as e:
                logger.exception(f"[NOVA] Error 3D: {e}")

        self.piper_modelo_path = os.path.join(self.base_dir, PIPER_MODEL)
        self.piper_config_path = os.path.join(self.base_dir, PIPER_CONFIG)
        self.piper_voice = None
        self._tts_fallo_permanente = False
        self.piper_cli_path = None
        self._tts_lock = threading.Lock()
        self._tts_en_proceso = False
        self._tts_verificado = False
        self._tts_verificando = False

        self.is_speaking = False
        self.is_processing = False
        self.is_listening = False
        self.closing = False

        self.model_chat = "llama3.2:3b"
        self.model_vision = "gemma3:4b"

        # NUEVO: modelo separado para CLASIFICAR intención y decidir si algo
        # es tarea_pc / tarea_web / chat. llama3.2:1b es demasiado chico
        # para esto — falla seguido detectando tareas complejas. Se recomienda
        # algo como "qwen2.5:3b-instruct" o "llama3.1:8b" si tu PC aguanta.
        # Si no defines uno, se usa model_chat (funciona, pero menos preciso).
        self.model_planificador = "qwen2.5:3b-instruct"

        # SOLUCIÓN #4: antes AMBOS modelos se cargaban con keep_alive=-1, es
        # decir, quedaban en RAM/VRAM para siempre desde el arranque. Eso
        # significa que "gemma3:4b" (pesado, se usa poco) competía
        # permanentemente por memoria con "llama3.2:1b" (chico, se usa en
        # cada respuesta de chat). Ahora solo el modelo de chat queda
        # residente indefinidamente; el modelo de visión se libera solo si
        # pasan 5 minutos sin usarse, y Ollama lo vuelve a cargar bajo demanda
        # la próxima vez que Nova necesite "ver".
        self.keep_alive_chat = -1
        self.keep_alive_vision = "5m"

        # ANTES: acá se cargaban Ollama + Vosk + faster-whisper de forma
        # SÍNCRONA — hasta 2-3 minutos bloqueando por completo el __init__
        # (mainloop() ni arrancaba, así que el saludo nunca podía dispararse,
        # aunque el cuerpo 3D sí aparecía porque corre en un proceso aparte).
        # Ahora arrancamos con valores por defecto inmediatos y la carga
        # pesada real se hace en un hilo de fondo: la app sigue su arranque
        # (audio, TTS, saludo) sin esperarla. Si el usuario intenta dictar
        # por voz antes de que termine, self.whisper_model/self.vosk_model
        # todavía van a ser None por un ratito — es un costo aceptable a
        # cambio de que Nova pueda saludar de inmediato.
        self.ollama_available = False
        self._ultimo_check_ollama = 0.0
        self.vosk_model = None
        self.whisper_model = None
        threading.Thread(target=self._cargar_ollama_y_stt_en_segundo_plano, daemon=True).start()
        logger.info(f"[ARRANQUE] Hilo Ollama/STT lanzado en segundo plano ({time.time() - self._t0_arranque:.1f}s)")

        self._ultima_respuesta_nova = None
        self._ultimo_prompt_usuario = None

        self.historial = []
        self.eventos = queue.Queue()

        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.energy_threshold = 150
        self.recognizer.pause_threshold = 1.2
        self.recognizer.phrase_threshold = 0.2
        self.recognizer.non_speaking_duration = 0.5

        self.microphone = None
        self.mic_available = False
        self.mic_calibrado = False
        self.mic_device_index = None

        self.ptt_active = False
        self.ptt_frames = []
        self.ptt_thread = None
        self.audio_pyaudio = None
        self.audio_rate = 16000
        self.audio_channels = 1
        self.audio_format = None
        self.audio_chunk = 1024

        if PYAUDIO_AVAILABLE:
            try:
                self.audio_pyaudio = pyaudio.PyAudio()
                self.audio_format = pyaudio.paInt16
            except Exception as e:
                logger.exception(f"[NOVA] PyAudio error: {e}")

        self.hotkey_listener = None

        # =========================================================
        # ★ OJO (PERCEPCIÓN VISUAL CONTINUA) ★
        # =========================================================
        # Se crea ANTES del bloque de mente_core: NovaMenteAdapter.iniciar()
        # revisa hasattr(self.nova, 'vision') and self.nova.vision en el
        # momento de arrancar, así que self.vision tiene que existir para
        # entonces o el "ojo" nunca se conecta.
        self.vision = None
        if NOVA_VISION_AVAILABLE:
            try:
                self.vision = NovaVision(base_dir=self.base_dir)
                print("[NOVA] 👁️ NovaVision instanciada")
            except Exception as e:
                logger.exception(f"[NOVA] Error instanciando NovaVision: {e}")
                self.vision = None
        else:
            print("[NOVA] NovaVision no disponible — Nova seguirá ciega (sin contexto de escritorio)")

        # =========================================================
        # ★ CEREBRO UNIFICADO (BUCLE DE PERCEPCIÓN-ACCIÓN CERRADO) ★
        # =========================================================
        self.mente_core = None
        if MENTE_CORE_AVAILABLE:
            try:
                self.mente_core = NovaMenteAdapter(
                    self,
                    db_path=os.path.join(self.base_dir, "nova_mente.db"),
                    chroma_path=os.path.join(self.base_dir, "nova_chroma_db"),
                    configuracion_path=os.path.join(self.base_dir, "Configuracion.json"),
                    memoria_path=os.path.join(self.base_dir, "Memoria.json"),
                    no_molestar_path=os.path.join(self.base_dir, "nova_no_molestar.json"),
                )
                
                if hasattr(self.mente_core.mente.ejecutor, "set_ollama_fallback"):
                    def _ollama_fallback_fn(texto_usuario, ocluir_historial=False):
                        return self._respuesta_ollama(texto_usuario, ocluir_historial=ocluir_historial)
                    self.mente_core.mente.ejecutor.set_ollama_fallback(_ollama_fallback_fn)

                if hasattr(self.mente_core.mente.ejecutor, "set_esta_hablando"):
                    self.mente_core.mente.ejecutor.set_esta_hablando(lambda: bool(getattr(self, "is_speaking", False)))

                # Con el cerebro unificado, es mente_core.mente.ejecutor quien
                # clasifica orden-vs-charla (ver Ejecutor._clasificar_orden_o_
                # charla en nova_mente_core.py) — le pasamos el mismo modelo
                # que ya configuraste acá arriba (self.model_planificador) en
                # vez de dejarlo en su default.
                if hasattr(self.mente_core.mente.ejecutor, "model_planificador"):
                    self.mente_core.mente.ejecutor.model_planificador = self.model_planificador

                self.mente_core.iniciar()
                print("[NOVA] ★ BUCLE DE CONTROL CEREBRAL CERRADO CON ÉXITO ★")
                logger.info(f"[ARRANQUE] mente_core listo ({time.time() - self._t0_arranque:.1f}s)")
                threading.Thread(target=self._precalentar_cache_tts, daemon=True).start()
            except Exception as e:
                logger.exception(f"[NOVA] Error iniciando Mente Core: {e}")
                self.mente_core = None
        else:
            print("[NOVA] Mente Core no disponible — modo legacy activado")

        if self.mente_core:
            self.historial = [{"role": "system", "content": self.mente_core.generar_contexto_sistema()}]
            # mic_device_index ahora vive en Configuracion.json -> perfil_usuario.tecnologia
            # (antes estaba en nova_memoria.json). Ver GestorPerfiles en nova_mente_core.py.
            _perfiles = self.mente_core.perfiles.cargar() or {}
            self.mic_device_index = _perfiles.get("usuario", {}).get("tecnologia", {}).get("mic_device_index")

        self.audio_engine = AudioEngine(self)
        logger.info(f"[ARRANQUE] AudioEngine creado ({time.time() - self._t0_arranque:.1f}s)")

        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=2048)
            print("[NOVA] Audio inicializado a 22050Hz, buffer 2048")
            logger.info(f"[ARRANQUE] pygame.mixer listo ({time.time() - self._t0_arranque:.1f}s)")
        except Exception as e:
            logger.exception(f"[NOVA] Audio init: {e}")
            try:
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=2048)
            except:
                logger.exception("Excepcion silenciada en __init__")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        import signal
        def signal_handler(sig, frame):
            print("\n[NOVA] Señal de interrupción recibida. Cerrando...")
            self.on_close()
        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, signal_handler)

        self.after(500, self.calibrar_microfono_inicio)
        self.after(700, self.iniciar_hotkey_ptt)
        self.after(900, self.procesar_cola)
        self.after(400, self._verificar_tts_v2)
        self._nova3d_estaba_vivo = bool(self.nova3d)
        self._nova3d_ultimo_reinicio = 0.0
        self._nova3d_reinicios = 0
        if self.nova3d:
            self.after(3000, self._monitorear_cuerpo_3d)
        logger.info(f"[ARRANQUE] __init__ termina, mainloop por arrancar ({time.time() - self._t0_arranque:.1f}s)")

    def _check_ollama(self):
        try:
            ollama.list()
            print("[NOVA] ✅ Ollama OK")
            return True
        except Exception:
            logger.exception("[NOVA] 🚨 Ollama offline")
            return False

    def _ollama_disponible_ahora(self, cooldown: float = 20.0) -> bool:
        """BUGFIX: reemplaza el uso directo de self.ollama_available (que se
        fijaba una sola vez al arrancar) en los puntos donde de verdad vamos
        a intentar hablarle a Ollama. Si la última vez que supimos su estado
        fue hace más de `cooldown` segundos, lo volvemos a chequear; si no,
        reutilizamos el resultado que ya teníamos para no meter una llamada
        de red extra en cada mensaje. Así, si Ollama se cae o se levanta a
        mitad de sesión, Nova se entera sin necesidad de reiniciar."""
        ahora = time.time()
        if ahora - getattr(self, "_ultimo_check_ollama", 0) >= cooldown:
            self.ollama_available = self._check_ollama()
            self._ultimo_check_ollama = ahora
        return self.ollama_available

    def _keep_alive_para(self, modelo: str):
        """SOLUCIÓN #4: devuelve cuánto tiempo debe quedar cargado un modelo en Ollama.
        El modelo de chat se queda para siempre (se usa constantemente);
        el de visión se libera solo tras un rato de inactividad."""
        return self.keep_alive_chat if modelo == self.model_chat else self.keep_alive_vision

    def _precargar_modelos(self):
        if not self.ollama_available:
            return
        for modelo in [self.model_chat, self.model_vision]:
            try:
                ollama.generate(
                    model=modelo, prompt="hola", options={"num_predict": 1},
                    keep_alive=self._keep_alive_para(modelo)
                )
                print(f"[NOVA] Modelo {modelo} precargado (keep_alive={self._keep_alive_para(modelo)})")
            except Exception as e:
                logger.exception(f"[NOVA] No se pudo precargar {modelo}: {e}")

    def _verificar_tts_v2(self):
        if self._tts_verificando or self._tts_verificado:
            return
        self._tts_verificando = True
        _t0 = time.time()
        logger.info("[ARRANQUE] _verificar_tts_v2: empieza")
        print("[NOVA] Verificando TTS...")
        try:
            self._verificar_tts_v2_interno()
        except Exception as e:
            # BLINDAJE: si CUALQUIER cosa no prevista explota acá adentro
            # (ej: un archivo de OneDrive que todavía no bajó y tarda en
            # abrirse), esto asegura que igual terminemos marcando el TTS
            # como verificado (en fallo) y programando el saludo. Antes,
            # una excepción no capturada acá dejaba _tts_verificado en
            # False para siempre, y hablar() reintentaba cada 500ms sin
            # parar, en silencio, sin ningún error visible en pantalla.
            logger.exception(f"[NOVA] _verificar_tts_v2 explotó sin control: {e}")
            self._tts_fallo_permanente = True
        finally:
            self._tts_verificado = True
            self._tts_verificando = False
            logger.info(f"[ARRANQUE] _verificar_tts_v2: termina ({time.time() - _t0:.1f}s) — fallo_permanente={self._tts_fallo_permanente}")
            self.after(200, self.saludo_inicial)

    def _verificar_tts_v2_interno(self):
        faltantes = []
        if not os.path.exists(self.piper_modelo_path):
            faltantes.append("Modelo .onnx")
        if not os.path.exists(self.piper_config_path):
            faltantes.append("Config .json")

        if faltantes:
            print(f"[NOVA] Faltan archivos TTS: {faltantes}")
            self._tts_fallo_permanente = True
            return

        modelo_size = os.path.getsize(self.piper_modelo_path)
        print(f"[NOVA] Tamaño modelo Piper: {modelo_size / 1024 / 1024:.1f} MB")
        if modelo_size < 10_000_000:
            print("[NOVA] 🚨 El modelo .onnx pesa menos de 10 MB. Está incompleto o corrupto.")
            self._tts_fallo_permanente = True
            return

        # Preferimos la ruta explícita dentro del venv antes que depender
        # de shutil.which (que solo funciona si el PATH del proceso incluye
        # .venv\Scripts — ver el fix de PATH al inicio del archivo). Esto
        # es un segundo blindaje: aunque el fix de PATH fallara por algún
        # motivo, esta ruta directa sigue encontrando piper.exe.
        _piper_exe_explicito = os.path.join(self.base_dir, ".venv", "Scripts", "piper.exe")
        self.piper_cli_path = (
            _piper_exe_explicito if os.path.isfile(_piper_exe_explicito)
            else (shutil.which("piper") or shutil.which("piper.exe"))
        )
        logger.info(f"[ARRANQUE] piper_cli_path = {self.piper_cli_path!r}")

        if PiperVoiceClass:
            try:
                self.piper_voice = PiperVoiceClass.load(self.piper_modelo_path)
                print("[NOVA] Modelo TTS precargado (librería)")
            except Exception as e:
                logger.exception(f"[NOVA] No se pudo precargar TTS librería: {e}")
                self.piper_voice = None
        else:
            # Este 'else' antes no existía: si el import de la librería de
            # Piper falló al arrancar el archivo (más arriba, fuera de esta
            # función), PiperVoiceClass queda en None y este bloque entero
            # se salteaba sin dejar rastro — ni un print, ni un log.
            logger.warning("[NOVA] PiperVoiceClass es None: la librería de Piper no se importó correctamente al arrancar.")
            self.piper_voice = None

        prueba_path = os.path.join(tempfile.gettempdir(), "nova_tts_prueba.wav")
        prueba_ok = False
        metodo_ok = ""

        if self.piper_voice:
            try:
                if os.path.exists(prueba_path):
                    os.remove(prueba_path)
                ok_prueba = self._piper_sintetizar_a_wav(self.piper_voice, "Hola.", prueba_path)
                if ok_prueba and os.path.exists(prueba_path) and os.path.getsize(prueba_path) > 5000:
                    prueba_ok = True
                    metodo_ok = "lib"
                    print("[NOVA] TTS librería funciona correctamente")
                else:
                    tam = os.path.getsize(prueba_path) if os.path.exists(prueba_path) else -1
                    logger.warning(f"[NOVA] TTS librería sintetizó pero el archivo de prueba salió chico/vacío (tamaño={tam} bytes)")
            except Exception as e:
                logger.exception(f"[NOVA] TTS lib precargada falló: {e}")
                self.piper_voice = None
        else:
            logger.warning("[NOVA] self.piper_voice es None, no se intenta síntesis por librería")

        if not prueba_ok and not getattr(self, 'piper_cli_path', None):
            # El otro hueco: si piper_cli_path quedó en None (shutil.which no
            # encontró piper.exe), este bloque de CLI se salteaba entero sin
            # avisar nada — la causa más probable es que la tarea programada
            # lanza pythonw.exe directo, sin pasar por Activate.ps1, así que
            # el PATH del proceso no incluye .venv\Scripts (donde vive
            # piper.exe), aunque en una terminal con el venv activado sí lo
            # encuentre.
            logger.warning("[NOVA] piper_cli_path es None: no se intenta síntesis por CLI (shutil.which no encontró piper.exe en PATH)")

        if not prueba_ok and getattr(self, 'piper_cli_path', None):
            try:
                cmd = [
                    self.piper_cli_path,
                    "--model", self.piper_modelo_path,
                    "--config", self.piper_config_path,
                    "--output_file", prueba_path,
                    "--length-scale", "1.0",
                ]
                texto_prueba = "Hola.\n"
                proc = subprocess.run(cmd, input=texto_prueba.encode(), capture_output=True, timeout=45)
                if proc.returncode == 0 and os.path.exists(prueba_path) and os.path.getsize(prueba_path) > 5000:
                    prueba_ok = True
                    metodo_ok = "CLI"
                    print("[NOVA] TTS CLI funciona correctamente")
            except Exception as e:
                logger.exception(f"[NOVA] TTS CLI prueba falló: {e}")

        if os.path.exists(prueba_path):
            try:
                os.remove(prueba_path)
            except:
                logger.exception("Excepcion silenciada en _verificar_tts_v2")

        if prueba_ok:
            print(f"[NOVA] ✅ TTS listo (método: {metodo_ok})")
            self._tts_fallo_permanente = False
        else:
            print("[NOVA] 🚨 TTS no funciona. Revisa el modelo.")
            self._tts_fallo_permanente = True



    def _tts_cache_path(self, texto: str):
        """Cache de audio para frases cortas que se repiten (los comentarios
        espontáneos del latido cognitivo, saludos, preguntas...). Se identifican
        por hash exacto del texto ya limpio, así que solo hace 'hit' cuando la
        frase es idéntica — las respuestas de chat normales, que casi nunca se
        repiten palabra por palabra, simplemente no generan cache útil y no
        estorban. Cachear evita la latencia de Piper para frases que Nova dice
        una y otra vez."""
        try:
            if not hasattr(self, "_tts_cache_dir"):
                self._tts_cache_dir = os.path.join(self.base_dir, "nova_tts_cache")
                os.makedirs(self._tts_cache_dir, exist_ok=True)
            clave = hashlib.md5(texto.strip().lower().encode("utf-8")).hexdigest()
            return os.path.join(self._tts_cache_dir, f"{clave}.wav")
        except Exception:
            return None

    def _piper_sintetizar_a_wav(self, voice, texto, path) -> bool:
        """Escribe la síntesis de Piper en un WAV válido en `path`.

        Distintas versiones de la librería piper-tts tienen APIs distintas
        para PiperVoice.synthesize(): las más nuevas devuelven un generador
        de fragmentos de audio (armamos el WAV nosotros), las más viejas
        escriben directo sobre el wave.Wave_write que se les pasa. El error
        real que vimos ('# channels not specified' al cerrar el wave writer)
        confirma que la versión instalada acá es la moderna: synthesize()
        no tocaba el wav_file para nada, por eso quedaba sin configurar.
        Probamos la moderna primero y si no aplica caemos a la vieja.
        """
        try:
            fragmentos = list(voice.synthesize(texto))
            if not fragmentos:
                logger.warning("[NOVA] Piper (API moderna) no devolvió fragmentos de audio")
                return False
            primero = fragmentos[0]
            sample_rate = getattr(primero, "sample_rate", None) or getattr(voice.config, "sample_rate", 22050)
            sample_width = getattr(primero, "sample_width", 2)
            channels = getattr(primero, "sample_channels", 1)
            with wave.open(path, "wb") as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                for frag in fragmentos:
                    wav_file.writeframes(frag.audio_int16_bytes)
            return os.path.exists(path) and os.path.getsize(path) > 0
        except (AttributeError, TypeError) as e:
            logger.debug(f"[NOVA] API moderna de Piper no aplica ({e}), probando API clásica")
            try:
                with wave.open(path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(getattr(voice.config, "sample_rate", 22050))
                    voice.synthesize(texto, wav_file)
                return os.path.exists(path) and os.path.getsize(path) > 0
            except Exception:
                logger.exception("[NOVA] Piper (API clásica) también falló")
                return False

    def _tts_sintetizar_chunk(self, texto, output_path):
        if self.closing:
            return False, None

        output_path = output_path
        texto = self.limpiar_para_tts(texto)
        if not texto:
            return False, None

        # Solo cacheamos frases cortas (las de latido/preguntas espontáneas
        # suelen rondar las 20-25 palabras); respuestas largas de chat casi
        # nunca se repiten igual, así que no vale la pena guardarlas en disco.
        cacheable = len(texto) <= 220
        cache_path = self._tts_cache_path(texto) if cacheable else None

        if cache_path and os.path.exists(cache_path) and os.path.getsize(cache_path) > 3000:
            try:
                shutil.copyfile(cache_path, output_path)
                return True, "cache"
            except Exception:
                logger.exception("Excepcion silenciada copiando desde cache TTS")

        try:
            if self.piper_voice and not self.closing:
                try:
                    ok_lib = self._piper_sintetizar_a_wav(self.piper_voice, texto, output_path)
                    if ok_lib and os.path.getsize(output_path) > 3000:
                        if cache_path:
                            try:
                                shutil.copyfile(output_path, cache_path)
                            except Exception:
                                logger.exception("Excepcion silenciada guardando cache TTS")
                        return True, "lib"
                    else:
                        logger.warning(f"[NOVA] TTS librería (precargada) generó archivo chico/vacío ({os.path.getsize(output_path) if os.path.exists(output_path) else -1} bytes)")
                except Exception as e:
                    logger.exception(f"[NOVA] TTS lib precargada error: {e}")
        except AttributeError:
            logger.exception("Excepcion silenciada en _tts_sintetizar_chunk")

        cli_path = getattr(self, 'piper_cli_path', None)
        if cli_path and os.path.exists(self.piper_modelo_path) and os.path.exists(self.piper_config_path):
            try:
                cmd = [
                    cli_path,
                    "--model", self.piper_modelo_path,
                    "--config", self.piper_config_path,
                    "--output_file", output_path,
                    "--length-scale", "1.0",
                ]
                texto_seguro = texto.strip() + "\n"
                
                proc = subprocess.run(
                    cmd,
                    input=texto_seguro.encode("utf-8"),
                    capture_output=True,
                    timeout=max(15, min(60, len(texto) * 0.8))
                )
                if proc.returncode == 0 and os.path.exists(output_path):
                    size = os.path.getsize(output_path)
                    if size > 1000:
                        if cache_path:
                            try:
                                shutil.copyfile(output_path, cache_path)
                            except Exception:
                                logger.exception("Excepcion silenciada guardando cache TTS (cli)")
                        return True, "cli"
                    else:
                        logger.warning(f"[NOVA] TTS CLI generó archivo muy pequeño ({size} bytes)")
                else:
                    stderr = proc.stderr.decode('utf-8', errors='ignore')[:200] if proc.stderr else ""
                    logger.warning(f"[NOVA] TTS CLI error (rc={proc.returncode}): {stderr}")
            except subprocess.TimeoutExpired:
                logger.exception("[NOVA] TTS CLI timeout")
            except Exception as e:
                logger.exception(f"[NOVA] TTS CLI excepción: {e}")

        if PiperVoiceClass and os.path.exists(self.piper_modelo_path) and not self.closing:
            try:
                voice = PiperVoiceClass.load(self.piper_modelo_path)
                ok_dyn = self._piper_sintetizar_a_wav(voice, texto, output_path)
                if ok_dyn and os.path.getsize(output_path) > 3000:
                    if cache_path:
                        try:
                            shutil.copyfile(output_path, cache_path)
                        except Exception:
                            logger.exception("Excepcion silenciada guardando cache TTS (lib_dyn)")
                    return True, "lib_dyn"
            except Exception as e:
                logger.exception(f"[NOVA] TTS lib dinámica error: {e}")

        logger.warning("[NOVA] _tts_sintetizar_chunk: ningún método de síntesis disponible pudo generar audio")
        return False, None

    def limpiar_para_tts(self, texto):
        texto = unicodedata.normalize('NFKC', texto)
        texto = re.sub(r'[😀-🙏🌀-🗿🚀-🛿🇦-🇿✂-➰Ⓜ-🉑]+', '', texto)
        texto = re.sub(r'[*_`~#|@^&]', '', texto)
        texto = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', texto)
        texto = re.sub(r'https?://\S+', '', texto)
        texto = re.sub(r'[^a-zA-ZáéíóúüñÁÉÍÓÚÜÑ0-9.,;:!?¿¡\-\' "]+', '', texto)
        texto = re.sub(r'\s+', ' ', texto).strip()

        # ANTES: texto[:150] cortaba a mitad de palabra/oración (p.ej. "...¿O p").
        # Ahora: si hace falta recortar, se corta en el último cierre de
        # oración (. ! ?) dentro del límite; si no hay ninguno razonablemente
        # cerca, se corta en el último espacio para no partir una palabra.
        LIMITE = 620
        if len(texto) <= LIMITE:
            return texto
        recorte = texto[:LIMITE]
        ultimo_cierre = max(recorte.rfind('.'), recorte.rfind('!'), recorte.rfind('?'))
        if ultimo_cierre >= LIMITE * 0.4:
            return recorte[:ultimo_cierre + 1]
        ultimo_espacio = recorte.rfind(' ')
        return recorte[:ultimo_espacio] if ultimo_espacio > 0 else recorte

    def _precalentar_cache_tts(self):
        """Sintetiza en segundo plano (sin reproducir nada) las frases fijas de
        personalidad de Nova, para que la primera vez que el latido cognitivo
        las use en la sesión ya salgan del caché en vez de esperar a Piper.
        Se ejecuta una sola vez al arrancar, con un pequeño respiro para no
        competir por CPU/GPU con la carga inicial de modelos."""
        try:
            time.sleep(8)
            if self.closing or not self.mente_core:
                return
            frases = []
            personalidad = getattr(self.mente_core, "personalidad", None)
            if personalidad:
                frases += list(getattr(personalidad, "frases_latido", []) or [])
                frases += list(getattr(personalidad, "preguntas_espontaneas", []) or [])
            nuevas = 0
            for frase in frases:
                if self.closing:
                    return
                if not self._tts_verificado or self._tts_fallo_permanente:
                    return
                texto_limpio = self.limpiar_para_tts(frase)
                if not texto_limpio:
                    continue
                cache_path = self._tts_cache_path(texto_limpio)
                if cache_path and os.path.exists(cache_path):
                    continue
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                        tmp_path = tmp.name
                    ok, _ = self._tts_sintetizar_chunk(frase, tmp_path)
                    if ok:
                        nuevas += 1
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                except Exception:
                    logger.exception("Excepcion silenciada precalentando TTS")
            if nuevas:
                print(f"[NOVA] 🔊 Cache de voz precalentado: {nuevas} frase(s) nueva(s) guardadas.")
        except Exception:
            logger.exception("Excepcion silenciada en _precalentar_cache_tts")

    def hablar(self, texto):
        if texto is None:
            return

        if not self._tts_verificado:
            self.after(500, lambda: self.hablar(texto))
            return
        if self._tts_fallo_permanente:
            # Antes esto era solo print() -> invisible bajo pythonw.exe (sin
            # consola). Es EXACTAMENTE el camino silencioso que probablemente
            # explica "el saludo se generó pero nunca sonó": si la verificación
            # de arranque marcó el TTS como fallido, hablar() corta acá mismo,
            # sin tocar el hilo de síntesis ni el motor de audio para nada.
            logger.warning(f"[NOVA] TTS falló permanentemente, solo texto: {texto}")
            return

        texto = self.limpiar_texto(texto)
        texto = self.limpiar_para_tts(texto)
        if not texto:
            return

        if not self._tts_lock.acquire(blocking=False):
            return

        if self._tts_en_proceso:
            try:
                self._tts_lock.release()
            except RuntimeError:
                logger.exception("Excepcion silenciada en hablar")
            return
        self._tts_en_proceso = True

        def _tts():
            try:
                self.is_speaking = True
                self.mostrar_estado("speaking")
                print(f"[NOVA] Hablando: '{texto}'")

                if self.nova3d:
                    try:
                        self.nova3d.speaking(True)
                    except:
                        logger.exception("Excepcion silenciada en _tts")

                audio_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                        audio_path = tmp.name

                    ok, _ = self._tts_sintetizar_chunk(texto, audio_path)
                    if ok:
                        self._tts_fallo_permanente = False
                        self.audio_engine.registrar_temporal(audio_path)
                        self.audio_engine.encolar(
                            audio_path,
                            on_start=None,
                            on_end=lambda: self._on_tts_end()
                        )
                    else:
                        self._on_tts_end()
                except Exception as e:
                    logger.exception(f"[NOVA] TTS error: {e}")
                    self._on_tts_end()
            except Exception as e:
                logger.exception(f"[NOVA] Error en hilo TTS: {e}")
                self._on_tts_end()

        threading.Thread(target=_tts, daemon=True).start()

    def _on_tts_end(self):
        if self.closing:
            return
        if self.nova3d:
            try:
                self.nova3d.speaking(False)
            except:
                logger.exception("Excepcion silenciada en _on_tts_end")
        self.is_speaking = False
        self._tts_en_proceso = False
        if self._tts_lock.locked():
            try:
                self._tts_lock.release()
            except RuntimeError:
                logger.exception("Excepcion silenciada en _on_tts_end")
        if not self.is_processing and not self.is_listening:
            self.mostrar_estado("idle")

    def mostrar_estado(self, estado):
        if not self.nova3d:
            return
        mapeo = {
            "idle": "idle", "escuchando": "listening", "pensando": "thinking",
            "speaking": "speaking", "error": "error",
        }
        try:
            self.nova3d.state(mapeo.get(estado, "idle"))
        except:
            logger.exception("Excepcion silenciada en mostrar_estado")

    def _cargar_ollama_y_stt_en_segundo_plano(self):
        """Chequeo de Ollama + precarga de modelos + Vosk + faster-whisper.

        Es exactamente la misma lógica que antes vivía directo en __init__,
        solo que ahora corre en un hilo daemon aparte para no bloquear el
        arranque de la ventana/audio/saludo (ver comentario en __init__).
        Cualquier código que lea self.whisper_model / self.vosk_model /
        self.ollama_available ya sabe manejarlos como None/False mientras
        esto termina, porque siempre pudieron fallar en carga (try/except
        original) y esos puntos de uso ya chequean 'if self.whisper_model'
        antes de usarlos.
        """
        try:
            self.ollama_available = self._check_ollama()
            self._ultimo_check_ollama = time.time()

            self._precargar_modelos()

            if VOSK_AVAILABLE and os.path.exists(VOSK_MODEL_PATH):
                try:
                    self.vosk_model = Model(VOSK_MODEL_PATH)
                    print("[NOVA] Vosk precargado")
                except Exception as e:
                    logger.exception(f"[NOVA] Error Vosk: {e}")

            if WHISPER_AVAILABLE:
                try:
                    print("[NOVA] Cargando faster-whisper...")
                    device = WHISPER_DEVICE
                    compute = WHISPER_COMPUTE_TYPE
                    if device == "auto":
                        try:
                            import torch
                            device = "cuda" if torch.cuda.is_available() else "cpu"
                            compute = "float16" if device == "cuda" else "int8"
                        except ImportError:
                            device = "cpu"
                            compute = "int8"
                    self.whisper_model = WhisperModel(
                        WHISPER_MODEL_SIZE,
                        device=device,
                        compute_type=compute,
                        download_root=os.path.join(self.base_dir, "whisper_models")
                    )
                    if device == "cuda":
                        # SOLUCIÓN: torch.cuda.is_available() puede devolver True
                        # (torch trae su propio runtime CUDA embebido) aunque
                        # falten las DLLs de cuBLAS/cuDNN que necesita
                        # ctranslate2 (el motor real de faster-whisper) para
                        # correr en GPU. Sin este chequeo, el desajuste no se
                        # detecta hasta el primer audio real del usuario, y ahí
                        # explota EN CADA transcripción — Nova nunca llega a usar
                        # Whisper y cae siempre a Vosk (bastante menos preciso)
                        # sin que quede claro por qué. Hacemos una transcripción
                        # de prueba silenciosa aquí, una sola vez al arrancar: si
                        # falla por las DLLs de CUDA, recargamos el mismo modelo
                        # pero en CPU y seguimos con eso.
                        try:
                            audio_prueba = np.zeros(16000, dtype=np.float32)
                            list(self.whisper_model.transcribe(audio_prueba, language="es")[0])
                        except Exception as e_gpu:
                            logger.warning(
                                f"[NOVA] faster-whisper en GPU falló al probarlo ({e_gpu}); "
                                "recargando en CPU para que no falle en cada frase del usuario."
                            )
                            self.whisper_model = WhisperModel(
                                WHISPER_MODEL_SIZE,
                                device="cpu",
                                compute_type="int8",
                                download_root=os.path.join(self.base_dir, "whisper_models")
                            )
                            device = "cpu"
                    print(f"[NOVA] ✅ faster-whisper listo ({WHISPER_MODEL_SIZE} en {device})")
                except Exception as e:
                    logger.exception(f"[NOVA] faster-whisper falló: {e}")
        except Exception as e:
            logger.exception(f"[NOVA] Error cargando Ollama/STT en segundo plano: {e}")

    def _monitorear_cuerpo_3d(self):
        """Chequeo periódico (cada 3s) de si el subproceso del cuerpo 3D
        sigue vivo. Un crash nativo de Qt6WebEngineCore (ej. violación de
        acceso por presión de memoria — es EXACTAMENTE lo que confirmamos
        que le pasaba a este proyecto) no deja ninguna excepción de Python
        para atrapar: el proceso simplemente desaparece. Antes, eso dejaba
        a Nova sin cuerpo para siempre, en silencio, hasta el próximo
        reinicio manual. Ahora se detecta y se reintenta solo, con un tope
        de 5 reinicios por sesión para no entrar en loop si el problema de
        fondo (memoria del sistema) sigue ahí."""
        if self.closing or not self.nova3d:
            return
        try:
            proceso_vivo = self.nova3d.esta_vivo()
        except Exception:
            proceso_vivo = False

        if self._nova3d_estaba_vivo and not proceso_vivo:
            logger.warning("[NOVA] 💥 El cuerpo 3D se cayó (proceso murió sin excepción de Python — probable crash nativo de Qt/Chromium).")
            ahora = time.time()
            if self._nova3d_reinicios < 5 and (ahora - self._nova3d_ultimo_reinicio) > 15.0:
                self._nova3d_reinicios += 1
                self._nova3d_ultimo_reinicio = ahora
                try:
                    self.nova3d.start()
                    print(f"[NOVA] 🔄 Reiniciando cuerpo 3D (intento {self._nova3d_reinicios}/5)...")
                except Exception as e:
                    logger.exception(f"[NOVA] Error reiniciando el cuerpo 3D: {e}")
            elif self._nova3d_reinicios >= 5:
                logger.warning("[NOVA] El cuerpo 3D se cayó 5 veces esta sesión — dejo de reintentar. Nova sigue funcionando por voz sin el avatar.")

        self._nova3d_estaba_vivo = proceso_vivo
        self.after(3000, self._monitorear_cuerpo_3d)

    def saludo_inicial(self):
        try:
            if self.nova3d:
                for _ in range(25):
                    if self.nova3d.is_ready():
                        break
                    time.sleep(0.2)
                else:
                    logger.warning("[NOVA] El cuerpo 3D no respondió 'listo' en 5s — saludo igual sin esperar más.")
            if self.mente_core:
                saludo = self.mente_core.obtener_saludo_inicial()
                if saludo:
                    self.hablar(saludo)
                else:
                    logger.warning("[NOVA] obtener_saludo_inicial() no devolvió ninguna frase — no hay saludo para hablar.")
        except Exception as e:
            logger.exception(f"[NOVA] saludo_inicial() falló ({e}) — antes esto se perdía en silencio por el stderr redirigido.")

    def _obtener_tasa_soportada(self, device_index):
        if not PYAUDIO_AVAILABLE or self.audio_pyaudio is None:
            return None
        try:
            info = self.audio_pyaudio.get_device_info_by_index(device_index)
            default_rate = int(info.get('defaultSampleRate', 44100))
            for rate in [16000, default_rate, 44100, 48000]:
                try:
                    test_stream = self.audio_pyaudio.open(
                        format=self.audio_format, channels=1, rate=rate,
                        input=True, input_device_index=device_index, frames_per_buffer=1024
                    )
                    test_stream.close()
                    return rate
                except Exception as e:
                    logger.debug(f"Tasa {rate}Hz no soportada en dispositivo {device_index}: {e}")
            return None
        except Exception:
            return None

    def listar_microfonos_disponibles(self):
        try:
            return sr.Microphone.list_microphone_names()
        except Exception as e:
            logger.exception(f"[NOVA] Error listando mics: {e}")
            return []

    def _es_dispositivo_fantasma(self, nombre):
        if not nombre or len(nombre.strip()) < 6:
            return True
        nombre_lower = nombre.lower().strip()
        virtuales = ["asignador", "mapper", "stereo mix", "mezcla est", "output",
                      "altavoz", "speaker", "headphones", "altavoces", "controlador primario"]
        return any(v in nombre_lower for v in virtuales)

    def elegir_microfono(self):
        try:
            mics = self.listar_microfonos_disponibles()
            if not mics:
                raise Exception("No se detectaron micrófonos")
            candidatos = []
            for i, nombre in enumerate(mics):
                if self._es_dispositivo_fantasma(nombre):
                    continue
                tasa = self._obtener_tasa_soportada(i)
                if tasa is None:
                    continue
                if "micrófono" in nombre.lower() or "microphone" in nombre.lower():
                    candidatos.insert(0, (i, nombre, tasa))
                else:
                    candidatos.append((i, nombre, tasa))
            if not candidatos and mics:
                tasa = self._obtener_tasa_soportada(0)
                if tasa:
                    candidatos.append((0, mics[0], tasa))
            return candidatos
        except Exception as e:
            logger.exception(f"[NOVA] Error eligiendo mic: {e}")
            raise

    def calibrar_microfono_inicio(self):
        try:
            print("[NOVA] Buscando micrófono...")
            candidatos = self.elegir_microfono()
            for i, nombre, tasa in candidatos:
                try:
                    mic = sr.Microphone(device_index=i)
                    with mic as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                        self.recognizer.energy_threshold = max(150, self.recognizer.energy_threshold * 0.8)
                    self.microphone = mic
                    self.mic_device_index = i
                    self.audio_rate = tasa
                    self.mic_available = True
                    self.mic_calibrado = True
                    print(f"[NOVA] ✅ Micrófono listo: {nombre} (índice {i}, {tasa}Hz). Umbral: {self.recognizer.energy_threshold:.0f}")
                    if self.mente_core:
                        self.mente_core.actualizar_perfil_usuario("tecnologia.mic_device_index", i)
                    self.after(500, self._test_captura_microfono)
                    return
                except Exception as e:
                    logger.debug(f"[NOVA] Mic [{i}] falló: {e}")
            raise Exception("Ningún micrófono funcional")
        except Exception as e:
            logger.exception(f"[NOVA] Error calibrando: {e}")
            logger.exception("[NOVA] Sin micrófono.")
            self.mic_available = False

    def _test_captura_microfono(self):
        if not self.mic_available or not PYAUDIO_AVAILABLE or np is None:
            return
        try:
            stream = self.audio_pyaudio.open(
                format=self.audio_format, channels=self.audio_channels,
                rate=self.audio_rate, input=True, input_device_index=self.mic_device_index,
                frames_per_buffer=self.audio_chunk
            )
            frames = []
            for _ in range(int(self.audio_rate / self.audio_chunk * 2)):
                data = stream.read(self.audio_chunk, exception_on_overflow=False)
                frames.append(data)
            stream.stop_stream()
            stream.close()
            raw = b''.join(frames)
            audio_np = np.frombuffer(raw, dtype=np.int16)
            max_amp = np.max(np.abs(audio_np))
            if max_amp < 30:
                print(f"[NOVA] 🚨 Mic sin señal (amp={max_amp}). Reconectando...")
                self.mic_device_index = None
                self.reintentar_microfono()
            else:
                print(f"[NOVA] ✅ Mic capturando OK (amp={max_amp})")
        except Exception as e:
            logger.exception(f"[NOVA] Test captura error: {e}")

    def reintentar_microfono(self):
        print("[NOVA] Reconectando...")
        self.mic_calibrado = False
        self.microphone = None
        self.mic_device_index = None
        if self.mente_core:
            self.mente_core.actualizar_perfil_usuario("tecnologia.mic_device_index", None)
        self.after(100, self.calibrar_microfono_inicio)

    def iniciar_hotkey_ptt(self):
        if not PYNPUT_AVAILABLE:
            print("[NOVA] Mantén 5 (foco en ventana)")
            return

        def on_press(key):
            try:
                if hasattr(key, 'char') and key.char == '5' and not self.ptt_active:
                    self.iniciar_ptt()
            except Exception:
                logger.exception("Excepcion silenciada en on_press")

        def on_release(key):
            try:
                if hasattr(key, 'char') and key.char == '5' and self.ptt_active:
                    self.detener_ptt()
            except Exception:
                logger.exception("Excepcion silenciada en on_release")

        self.hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.hotkey_listener.start()
        print("[NOVA] Listo. Mantén 5 para hablar.")

    def iniciar_ptt(self):
        if self.closing or not self.mic_available or self.is_processing:
            return
        self.ptt_active = True
        self.ptt_frames = []
        self.is_listening = True
        self.mostrar_estado("escuchando")
        print("[NOVA] 🎙️ Escuchando... (suelta 5)")
        if PYAUDIO_AVAILABLE and self.audio_pyaudio:
            self.ptt_thread = threading.Thread(target=self._ptt_record_pyaudio, daemon=True)
        else:
            self.ptt_thread = threading.Thread(target=self._ptt_record_hybrid, daemon=True)
        self.ptt_thread.start()

    def detener_ptt(self):
        self.ptt_active = False

    def _ptt_record_pyaudio(self):
        stream = None
        try:
            stream = self.audio_pyaudio.open(
                format=self.audio_format, channels=self.audio_channels,
                rate=self.audio_rate, input=True, input_device_index=self.mic_device_index,
                frames_per_buffer=self.audio_chunk
            )
            while self.ptt_active:
                try:
                    data = stream.read(self.audio_chunk, exception_on_overflow=False)
                    self.ptt_frames.append(data)
                except Exception:
                    break
        except Exception as e:
            logger.exception(f"[NOVA] Stream PTT error: {e}")
            self.ptt_active = False
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except:
                    logger.exception("Excepcion silenciada en _ptt_record_pyaudio")
        self._procesar_audio_ptt()

    def _ptt_record_hybrid(self):
        audios = []
        try:
            with self.microphone as source:
                while self.ptt_active:
                    try:
                        audio = self.recognizer.listen(source, timeout=1.0, phrase_time_limit=0.8)
                        audios.append(audio)
                    except sr.WaitTimeoutError:
                        continue
        except Exception as e:
            logger.exception(f"[NOVA] Híbrido error: {e}")
        if audios:
            combined_raw = b''.join([a.get_raw_data() for a in audios])
            audio_temp = sr.AudioData(combined_raw, audios[0].sample_rate, audios[0].sample_width)
            wav_16k = self._preparar_audio_vosk(audio_temp)
            if wav_16k:
                self.eventos.put(sr.AudioData(wav_16k, 16000, 2))
        self.is_listening = False
        if not self.is_processing and not self.is_speaking and not self.closing:
            self.mostrar_estado("idle")
            print("[NOVA] Listo. Mantén 5 para hablar." if self.mic_available else "[NOVA] Sin micrófono.")

    def _procesar_audio_ptt(self):
        if not self.ptt_frames:
            self.is_listening = False
            print("[NOVA] Muy corto. Mantén 5.")
            return
        raw_audio = b''.join(self.ptt_frames)
        if self.audio_rate != 16000 and np is not None:
            try:
                audio_np = np.frombuffer(raw_audio, dtype=np.int16)
                ratio = 16000 / self.audio_rate
                new_len = int(len(audio_np) * ratio)
                if new_len > 0:
                    indices = np.linspace(0, len(audio_np) - 1, new_len)
                    audio_np = np.interp(indices, np.arange(len(audio_np)), audio_np)
                    audio_np = np.clip(audio_np, -32768, 32767).astype(np.int16)
                    raw_audio = audio_np.tobytes()
            except Exception as e:
                logger.exception(f"[NOVA] Re-muestreo error: {e}")
        if np is not None:
            try:
                audio_np = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32)
                audio_np = np.clip(audio_np * 1.5, -32768, 32767).astype(np.int16)
                raw_audio = audio_np.tobytes()
            except Exception:
                logger.exception("Excepcion silenciada en _procesar_audio_ptt")
        try:
            import noisereduce as nr
            if np is not None:
                audio_np = np.frombuffer(raw_audio, dtype=np.int16)
                audio_np = nr.reduce_noise(y=audio_np, sr=16000, prop_decrease=0.85)
                raw_audio = audio_np.astype(np.int16).tobytes()
        except ImportError:
            logger.debug("Import opcional no disponible (ImportError) en _procesar_audio_ptt")
        except Exception:
            logger.exception("Excepcion silenciada en _procesar_audio_ptt")
        self.eventos.put(sr.AudioData(raw_audio, 16000, 2))
        self.is_listening = False
        print("[NOVA] Procesando...")

    def _preparar_audio_vosk(self, audio_data):
        try:
            dtype = np.int16 if audio_data.sample_width == 2 else np.int8
            raw = np.frombuffer(audio_data.get_raw_data(), dtype=dtype)
            if audio_data.sample_rate != 16000:
                ratio = 16000 / audio_data.sample_rate
                new_len = int(len(raw) * ratio)
                if new_len > 0:
                    indices = np.linspace(0, len(raw) - 1, new_len)
                    raw = np.interp(indices, np.arange(len(raw)), raw)
            raw = np.clip(raw, -32768, 32767).astype(np.int16)
            return raw.tobytes()
        except Exception as e:
            logger.exception(f"[NOVA] Preparar audio error: {e}")
            return None

    def reconocer_audio(self, audio_data):
        texto = None
        confianza = 0.0

        if self.whisper_model:
            try:
                if hasattr(audio_data, 'get_raw_data'):
                    raw = np.frombuffer(audio_data.get_raw_data(), dtype=np.int16)
                    audio_np = raw.astype(np.float32) / 32768.0
                    sr_rate = audio_data.sample_rate
                elif isinstance(audio_data, bytes):
                    audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
                    sr_rate = 16000
                elif isinstance(audio_data, np.ndarray):
                    audio_np = audio_data.astype(np.float32)
                    if audio_np.max() > 1.0:
                        audio_np = audio_np / 32768.0
                    sr_rate = 16000
                else:
                    audio_np, sr_rate = None, 16000

                if sr_rate != 16000 and audio_np is not None and len(audio_np) > 0:
                    ratio = 16000 / sr_rate
                    new_len = int(len(audio_np) * ratio)
                    if new_len > 0:
                        indices = np.linspace(0, len(audio_np) - 1, new_len)
                        audio_np = np.interp(indices, np.arange(len(audio_np)), audio_np)

                if audio_np is not None and len(audio_np) > 8000:
                    segments, _ = self.whisper_model.transcribe(
                        audio_np,
                        language="es",
                        beam_size=5,
                        vad_filter=True,
                        vad_parameters=dict(
                            threshold=0.5,
                            min_speech_duration_ms=250,
                            min_silence_duration_ms=500,
                            speech_pad_ms=200
                        ),
                        condition_on_previous_text=True,
                        without_timestamps=True
                    )
                    textos = []
                    for segment in segments:
                        textos.append(segment.text.strip())
                    texto = " ".join(textos).strip().lower()
                    if texto and len(texto) > 2:
                        print(f'[NOVA] Whisper: "{texto}"')
                        return texto
            except Exception as e:
                logger.exception(f'[NOVA] Whisper error: {e}')

        if self.vosk_model:
            try:
                wav_16k = self._preparar_audio_vosk(audio_data)
                if wav_16k:
                    rec = KaldiRecognizer(self.vosk_model, 16000)
                    rec.AcceptWaveform(wav_16k)
                    res = json.loads(rec.Result())
                    texto = res.get("text", "").lower().strip()
                    confianza = min(1.0, len(texto) / 20.0) if texto else 0.0
                    if texto and len(texto) > 2:
                        print(f'[NOVA] Vosk: "{texto}" (conf~{confianza:.2f})')
                        if not self._parece_basura(texto):
                            return texto
            except Exception as e:
                logger.exception(f'[NOVA] Vosk error: {e}')

        try:
            texto_google = self.recognizer.recognize_google(audio_data, language="es-CO").lower().strip()
            if texto_google and len(texto_google) > 2:
                print(f'[NOVA] Google: "{texto_google}"')
                return texto_google
        except sr.UnknownValueError:
            logger.exception("Excepcion silenciada en reconocer_audio")
        except sr.RequestError:
            logger.exception("[NOVA] Sin internet - Google STT no disponible")
        except Exception as e:
            logger.exception(f'[NOVA] Google STT error: {e}')

        return None

    def _parece_basura(self, texto):
        if not texto:
            return True
        basura = ["incendiadas", "como es", "nada como", "el el el", "un un un", "la la la",
                   "aaaaaaaa", "eeeeeee", "ooooooo", "xxxxxx", "123456"]
        for b in basura:
            if b in texto:
                return True
        palabras = texto.split()
        if not palabras:
            return True
        cortas = sum(1 for p in palabras if len(p) <= 2)
        if cortas / len(palabras) > 0.6:
            return True
        return False

    def procesar_mensaje_con_adjuntos(self, texto: str, archivos: list):
        """Punto de entrada para mensajes que llegan del panel de chat del
        cuerpo 3D (NovaChatDialog en nova_3d_controller.py), que pueden traer
        imágenes y/o documentos adjuntos. Las imágenes van directo al modelo
        de visión (mismo modelo que ya usa Nova para 'ver pantalla', pero
        apuntado al archivo elegido en vez de una captura en vivo) — una
        imagen por mensaje, para mantenerlo simple. Los documentos (Word,
        texto plano) se leen y su contenido se agrega como contexto ANTES
        del texto del usuario, para que Nova responda ya sabiendo de qué se
        trata, sin que el usuario tenga que describirlo por su cuenta."""
        if not archivos:
            self.procesar_texto(texto)
            return

        EXTENSIONES_IMAGEN = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        imagenes = [a for a in archivos if os.path.splitext(a)[1].lower() in EXTENSIONES_IMAGEN]
        documentos = [a for a in archivos if a not in imagenes]

        if imagenes:
            threading.Thread(
                target=self._responder_con_imagen_adjunta,
                args=(texto, imagenes[0]), daemon=True
            ).start()
            return

        contexto_extra = []
        for ruta in documentos:
            ext = os.path.splitext(ruta)[1].lower()
            try:
                if ext == ".docx" and NOVA_SKILLS_AVAILABLE:
                    r = self._skill("leer_texto_word", ruta)
                    if r.get("ok"):
                        contexto_extra.append(f"[Contenido de {os.path.basename(ruta)}]:\n{str(r['resultado'])[:3000]}")
                    else:
                        contexto_extra.append(f"[No pude leer {os.path.basename(ruta)}: {r.get('error')}]")
                elif ext in (".txt", ".md"):
                    with open(ruta, "r", encoding="utf-8", errors="replace") as f:
                        contexto_extra.append(f"[Contenido de {os.path.basename(ruta)}]:\n{f.read()[:3000]}")
                elif ext == ".pdf" and PYPDF_AVAILABLE:
                    lector = PdfReader(ruta)
                    texto_pdf = "\n".join(pagina.extract_text() or "" for pagina in lector.pages)
                    if texto_pdf.strip():
                        contexto_extra.append(f"[Contenido de {os.path.basename(ruta)}]:\n{texto_pdf[:3000]}")
                    else:
                        contexto_extra.append(f"[El PDF '{os.path.basename(ruta)}' no tiene texto legible (¿es un escaneo/imagen?)]")
                else:
                    contexto_extra.append(f"[Se adjuntó '{os.path.basename(ruta)}' — todavía no sé leer ese tipo de archivo]")
            except Exception as e:
                logger.exception(f"[NOVA] Error leyendo adjunto {ruta}: {e}")
                contexto_extra.append(f"[No pude leer el archivo adjunto {os.path.basename(ruta)}]")

        texto_final = texto or "Mirá este archivo que te mando."
        if contexto_extra:
            texto_final = "\n\n".join(contexto_extra) + "\n\n" + texto_final
        self.procesar_texto(texto_final)

    def _responder_con_imagen_adjunta(self, texto: str, ruta_imagen: str):
        """Le manda una imagen puntual (elegida por el usuario, no una
        captura de pantalla) al modelo de visión, junto con lo que haya
        escrito. Corre en su propio hilo para no bloquear procesar_cola()
        mientras el modelo de visión piensa."""
        if not os.path.isfile(ruta_imagen):
            self.hablar("Esa imagen que me mandaste no la pude encontrar.")
            return
        if not self._ollama_disponible_ahora():
            self.hablar("Se me fue la conexión con Ollama, no puedo mirar la imagen ahora.")
            return
        try:
            self.mostrar_estado("pensando")
            res = ollama.chat(
                model=self.model_vision,
                messages=[{
                    "role": "user",
                    "content": texto or "Describime qué ves en esta imagen.",
                    "images": [ruta_imagen],
                }],
                options={"temperature": 0.4, "num_predict": 220},
                keep_alive=self._keep_alive_para(self.model_vision),
            )
            msg = res["message"]["content"].strip()
            if self.mente_core:
                try:
                    self.mente_core.registrar_interaccion(
                        f"[imagen adjunta: {os.path.basename(ruta_imagen)}] {texto}", msg
                    )
                except Exception:
                    logger.exception("Excepcion silenciada registrando interacción de imagen adjunta")
            self.hablar(msg)
        except Exception as e:
            logger.exception(f"[NOVA] Error respondiendo con imagen adjunta: {e}")
            self.hablar("Uy, algo falló mirando esa imagen. ¿Podés intentarlo de nuevo?")
        finally:
            if not self.is_processing and not self.is_listening:
                self.mostrar_estado("idle")

    def necesita_vision(self, prompt):
        t = prompt.lower()
        palabras = [
            "ves", "veo", "pantalla", "imagen", "captura", "screenshot",
            "muestra", "qué hay", "describe", "qué es esto", "qué es eso",
            "mira", "observa", "examina", "analiza", "revisa",
            "mi pantalla", "mi escritorio", "la pantalla", "la imagen"
        ]
        return any(p in t for p in palabras)

    def necesita_respuesta_larga(self, prompt: str) -> bool:
        """Por defecto Nova responde corto (ver personalidad en Configuracion.json).
        Esto detecta la EXCEPCIÓN real: el usuario pidió explícitamente que
        explique, liste, o detalle algo — ahí sí le damos más margen de
        num_predict. Para cualquier otro mensaje, el tope se queda bajo: no
        es que 'confiemos' en que el modelo se porte breve, es que
        directamente no le damos presupuesto de tokens para extenderse."""
        t = prompt.lower()
        disparadores = [
            "explica", "explícame", "explicame", "detalla", "detállame",
            "cuéntame más", "cuentame mas", "cuáles son", "cuales son",
            "enumera", "enuméra", "lista", "todas tus habilidades",
            "qué sabes hacer", "que sabes hacer", "cómo funciona",
            "como funciona", "por qué", "porque", "paso a paso",
            "en detalle", "con más detalle", "con mas detalle",
            "dame más información", "dame mas informacion",
        ]
        return any(d in t for d in disparadores)

    def procesar_cola(self):
        if self.closing:
            return
        try:
            while not self.eventos.empty():
                item = self.eventos.get_nowait()
                if isinstance(item, sr.AudioData):
                    texto = self.reconocer_audio(item)
                    if texto:
                        self.procesar_texto(texto)
                    else:
                        print("[NOVA] No te escuché bien. Habla más cerca o ajusta el micrófono.")
                elif isinstance(item, tuple) and len(item) == 2 and item[0] == "__HABLAR_AUTONOMO__":
                    # Habla espontánea generada por el núcleo cognitivo (hilo de fondo).
                    # Se procesa aquí, en el hilo principal, porque hablar()/mostrar_estado()
                    # tocan la UI de Tkinter y solo son seguras desde este hilo.
                    if MENTE_CORE_AVAILABLE:
                        debug_mente(f"[NOVA] 🔊 DEBUG: cola recibió habla autónoma -> '{item[1]}'")
                    self.hablar(item[1])
                elif isinstance(item, str):
                    self.procesar_texto(item)
        except Exception as e:
            logger.exception(f"[NOVA] Error cola: {e}")
        finally:
            if not self.closing:
                self.after(120, self.procesar_cola)

        if self.nova3d:
            try:
                eventos = self.nova3d.poll_events()
                for ev in eventos:
                    tipo_ev = ev.get('type') if isinstance(ev, dict) else None

                    if tipo_ev == 'chat':
                        msg = ev.get('text')
                        if msg == '__SHUTDOWN__':
                            print("[NOVA] 🛑 INICIANDO CIERRE...")
                            self.closing = True
                            self.ptt_active = False

                            if self.mente_core:
                                try:
                                    self.mente_core.detener()
                                except:
                                    logger.exception("Excepcion silenciada en procesar_cola")

                            time.sleep(0.3)

                            try:
                                self.audio_engine._detener_inmediato()
                            except:
                                logger.exception("Excepcion silenciada en procesar_cola")

                            try:
                                self.destroy()
                            except:
                                logger.exception("Excepcion silenciada en procesar_cola")

                            sys.exit(0)

                        elif msg or ev.get('archivos'):
                            self.procesar_mensaje_con_adjuntos(msg or "", ev.get('archivos') or [])

                    elif tipo_ev == 'dnd':
                        # Eventos del menú "No molestar" del cuerpo 3D (clic derecho).
                        # Aquí es donde de verdad se aplica el cambio, sobre el
                        # GestorNoMolestar que vive en nova_mente_core.py.
                        if not self.mente_core:
                            continue
                        accion = ev.get('action')
                        try:
                            if accion == 'toggle':
                                activo = self.mente_core.dnd_toggle()
                                print(f"[NOVA] 🌙 No molestar {'activado' if activo else 'desactivado'} desde el menú 3D")
                            elif accion == 'add' and ev.get('app'):
                                self.mente_core.dnd_agregar_app(ev['app'])
                            elif accion == 'remove' and ev.get('app'):
                                self.mente_core.dnd_quitar_app(ev['app'])
                        except Exception:
                            logger.exception("Excepcion silenciada procesando evento dnd")
            except Exception:
                logger.exception("Excepcion silenciada en procesar_cola")

    def _analizar_feedback_implicito(self, prompt: str) -> Dict:
        t = prompt.lower().strip()

        senales_negativas = ['no', 'eso no', 'incorrecto', 'mal', 'otra vez',
                             'repito', 'te dije', 'no entendiste', 'quise decir']
        senales_positivas = ['sí', 'exacto', 'perfecto', 'gracias', 'bien', 'correcto',
                             'claro', 'eso es', 'me sirve']

        cambio_tono = 'neutral'
        if any(s in t for s in senales_negativas):
            cambio_tono = 'negativo'
        elif any(s in t for s in senales_positivas):
            cambio_tono = 'positivo'

        usuario_repitio = False
        if hasattr(self, '_ultimo_prompt_usuario') and self._ultimo_prompt_usuario:
            palabras_antes = set(self._ultimo_prompt_usuario.lower().split())
            palabras_ahora = set(t.split())
            if len(palabras_ahora) > 0:
                interseccion = palabras_antes & palabras_ahora
                similitud = len(interseccion) / len(palabras_ahora)
                usuario_repitio = similitud > 0.7 and len(t) > 10

        return {
            'cambio_tono_usuario': cambio_tono,
            'usuario_repitio': usuario_repitio,
            'tiempo_hasta_siguiente': 0
        }

    def _set_ultima_respuesta(self, respuesta: str):
        self._ultima_respuesta_nova = respuesta

    def limpiar_texto(self, texto):
        return re.sub(r"\s+", " ", texto.strip())

    # =========================================================
    # ★ ARCO REFLEJO SOMÁTICO (SEGURIDAD ANTE LATENCIA) ★
    # =========================================================
    def _es_reflejo_mecanico(self, prompt: str) -> bool:
        """
        Simula el arco reflejo somático humano:
        Acciones físicas mecánicas instantáneas que no deben pasar por el 
        lóbulo frontal (Ollama) para no generar latencia robótica.
        """
        t = prompt.lower().strip()
        tiene_numero = any(c.isdigit() for c in t)
        mecanicos = [
            "silencio", "mute",
            "minimiza", "maximiza", "cierra la ventana", "bloc de notas",
            "calculadora", "captura", "pantallazo", "abre youtube", "abre google"
        ]
        # "sube/baja el volumen" SOLO es reflejo mecánico (pasos fijos) si NO
        # trae un número — "sube el volumen a 80" necesita el camino
        # inteligente (con la skill establecer_volumen), no un empujón fijo
        # de 5 pasos que ignora el "80" por completo.
        if not tiene_numero:
            mecanicos += ["sube el volumen", "baja el volumen"]
        return any(m in t for m in mecanicos)

    # Palabras que interpretamos como sí/no cuando Nova está esperando
    # confirmación de una propuesta pendiente (ver NucleoCognitivoExtendido
    # .confirmar_propuesta_pendiente en nova_mente_core.py). Deliberadamente
    # simple y en español: esto NO es un parser de intención general, es
    # solo el sí/no puntual para resolver la propuesta que Nova ya dijo
    # en voz alta.
    _AFIRMACIONES = {
        "si", "sí", "dale", "ok", "okay", "listo", "hacelo", "hazlo",
        "adelante", "obvio", "bueno", "claro", "va", "sisi", "simon",
    }
    _NEGACIONES = {
        "no", "nel", "nop", "negativo", "todavia no", "todavía no",
        "mejor no", "ahora no", "despues", "después",
    }

    def _interpretar_si_no(self, prompt: str) -> Optional[bool]:
        """Devuelve True/False si el prompt es un sí/no claro y corto,
        None si no se puede interpretar así (para no confundir una frase
        larga y ambigua con una confirmación)."""
        t = unicodedata.normalize("NFKD", prompt.strip().lower())
        t = "".join(c for c in t if not unicodedata.combining(c))
        t = t.strip(" .!¡¿?")
        if not t or len(t.split()) > 4:
            return None
        if t in self._AFIRMACIONES:
            return True
        if t in self._NEGACIONES:
            return False
        return None

    def _intentar_resolver_propuesta_pendiente(self, prompt: str) -> bool:
        """Si Nova está esperando que el usuario confirme una meta propia
        (ver Ejecutor._proponer_confirmacion en nova_mente_core.py) y este
        prompt se puede leer como un sí/no, resuelve la propuesta acá y
        devuelve True para que procesar_texto() corte el flujo normal de
        conversación. Si no hay propuesta pendiente, o el prompt no es un
        sí/no claro, devuelve False y todo sigue como siempre (por ejemplo,
        el usuario puede seguir charlando de otra cosa sin que Nova se
        quede esperando una respuesta puntual)."""
        if not self.mente_core:
            return False

        nucleo = getattr(self.mente_core, "mente", None)
        if not nucleo or not hasattr(nucleo, "hay_propuesta_pendiente"):
            return False

        try:
            propuesta = nucleo.hay_propuesta_pendiente()
        except Exception:
            logger.exception("[NOVA] Error consultando propuesta pendiente")
            return False

        if not propuesta:
            return False

        aceptar = self._interpretar_si_no(prompt)
        if aceptar is None:
            # Hay propuesta pendiente pero el usuario no respondió con un
            # sí/no reconocible: la dejamos pendiente y seguimos con el
            # flujo normal (puede estar hablando de otra cosa).
            return False

        try:
            resultado = nucleo.confirmar_propuesta_pendiente(aceptar)
        except Exception:
            logger.exception("[NOVA] Error resolviendo propuesta pendiente")
            self.hablar("Uy, algo falló resolviendo eso. Mejor lo dejamos.")
            return True

        mensaje = resultado.get("mensaje") if isinstance(resultado, dict) else None
        self.hablar(mensaje or ("Listo." if aceptar else "Dale, no lo hago."))
        return True

    def procesar_texto(self, prompt):
        """
        Anfitrión del Bucle Cerrado: Delega el input al cerebro (MenteCore).
        Solo si es un Reflejo Somático instantáneo o el cerebro falla, 
        actúa de forma local.
        """
        prompt = self.limpiar_texto(prompt or "")
        if not prompt or self.is_processing:
            return

        print(f"Tú: {prompt}")

        # 0. ¿Nova está esperando un sí/no sobre una meta propia que
        # propuso? Si es así y este prompt lo resuelve, cortamos acá:
        # no queremos que "sí, dale" termine mandado al LLM como si fuera
        # el inicio de una conversación nueva.
        if self._intentar_resolver_propuesta_pendiente(prompt):
            return

        # 1. Metacognición: Evaluar calidad de la respuesta anterior
        if self.mente_core and self._ultima_respuesta_nova and self._ultimo_prompt_usuario:
            feedback = self._analizar_feedback_implicito(prompt)
            if hasattr(self.mente_core, 'metacognicion'):
                self.mente_core.metacognicion.evaluar_calidad_respuesta(
                    self._ultimo_prompt_usuario,
                    self._ultima_respuesta_nova,
                    feedback
                )

        self._ultimo_prompt_usuario = prompt
        self._ultima_respuesta_nova = None
        
    
        
        # 2. ★ BUCLE CERRADO: ENVIAMOS EL ESTÍMULO A LA MENTE ★
    
        if self.mente_core:
            # FIX (unificación de cerebro): antes esta rama SIEMPRE llamaba
            # a self.mente_core.usuario_habla(prompt) (que dispara el
            # latido cognitivo -> RESPONDER_USUARIO -> puede hablar) Y AL
            # MISMO TIEMPO lanzaba un hilo separado (_decidir_y_responder)
            # que también podía decidir ejecutar una skill o generar charla
            # y hablar. Los dos caminos no se enteraban uno del otro:
            # de ahí las respuestas dobles/contradictorias ("Listo, ya
            # ejecuté X" seguido de "no puedo hacer eso").
            #
            # Ahora mente_core.mente.ejecutor (ver nova_mente_core.py) es
            # el ÚNICO que decide y habla para texto del usuario — ya sabe
            # clasificar orden-vs-charla por su cuenta (Ejecutor._intentar_
            # como_accion), corriendo siempre en su propio hilo del latido,
            # de a una intención por vez. _decidir_y_responder / responder_llm
            # quedan como respaldo legado (solo chat, sin ejecutar skills)
            # para cuando mente_core no está activo (ver más abajo, sección 3).
            if self._es_reflejo_mecanico(prompt) and self.ejecutar_comandos(prompt):
                # Comando fijo (regex, sin LLM) ya resuelto y anunciado acá
                # mismo: solo dejamos rastro, SIN mandarlo también al
                # latido cognitivo (para no generar una segunda respuesta).
                self.mente_core.registrar_interaccion_directa(prompt)
            else:
                self.mente_core.usuario_habla(prompt)
            return
    
    
    
        # 3. FALLBACK LEGACY (Si la Mente Core estuviera apagada por error)
        try:
            self._extraer_datos_perfil(prompt)
        except Exception as e:
            logger.exception(f"[NOVA] Error extrayendo perfil: {e}")

        if prompt.lower().startswith("recuerda que "):
            hecho = prompt[13:].strip()
            if hecho:
                if self.nova3d:
                    try: self.nova3d.state('celebrating')
                    except: logger.exception("Excepcion silenciada en procesar_texto")
                self.hablar(f"Apuntado. Recordaré que {hecho}")
            return

        if "mi nombre es " in prompt.lower():
            try:
                nombre = prompt.lower().split("mi nombre es ")[-1].strip().split()[0]
                nombre_cap = nombre.capitalize()
                if self.nova3d:
                    try: self.nova3d.expression('happy', 1.0)
                    except: logger.exception("Excepcion silenciada en procesar_texto")
                self.hablar(f"Encantada, {nombre_cap}. Ya lo tengo guardado.")
            except Exception:
                self.hablar("Ups, no pude guardar tu nombre.")
            return

        if self.ejecutar_comandos(prompt):
            return

        if not self._ollama_disponible_ahora():
            self.hablar("Se me fue la conexión con mi cerebro. Dame un momento e inténtalo de nuevo.")
            return

        if self.nova3d:
            try: self.nova3d.state('thinking')
            except: logger.exception("Excepcion silenciada en procesar_texto")

        threading.Thread(target=self._decidir_y_responder, args=(prompt,), daemon=True).start()

    def _decidir_y_responder(self, prompt: str):
        """
        Punto de entrada del camino LEGACY cuando Mente Core no está
        procesando directamente el mensaje. Los comandos fijos de
        ejecutar_comandos() tienen prioridad; todo lo demás va al chat.

        El procesamiento de órdenes con skills queda centralizado en
        nova_mente_core.py, que es el único planificador de acciones.
        """
        try:
            if self.ejecutar_comandos(prompt):
                return
            self.responder_llm(prompt)
        except Exception as e:
            logger.exception(f"[NOVA] Error procesando mensaje: {e}")
            self.responder_llm(prompt)

    def _extraer_datos_perfil(self, texto):
        t = texto.lower()

        m = re.search(r"(?:me gusta|me encanta|amo)\s+(?:el\s+|la\s+)?(?:música\s+)?(rock|pop|rap|jazz|clásica|reggaeton|techno|metal|salsa|bachata|indie)\s*(?:de\s+)?([^.,;]{2,40})", t)
        if m:
            genero = m.group(1)
            detalle = m.group(2).strip()
            if self.mente_core:
                self.mente_core.actualizar_perfil_usuario("preferencias.musica", f"{genero}: {detalle}")

        m = re.search(r"(?:me gusta comer|mi comida favorita es|amo)\s+([^.,;]{2,30})", t)
        if m:
            if self.mente_core:
                self.mente_core.actualizar_perfil_usuario("preferencias.comida", m.group(1).strip())

        m = re.search(r"(?:te llamo|te digo|me refiero a ti como)\s+([a-záéíóúñ]{2,15})", t)
        if m:
            nombre = m.group(1).strip()
            if nombre not in ["nova", "no", "mi"]:
                if self.mente_core:
                    # 'como me llama' ahora vive en Memoria.json -> relacion
                    # (antes en perfiles_nova.json -> usuario.relacion_con_nova).
                    self.mente_core.memoria.setdefault("relacion", {})["como_le_dice_alex_a_nova"] = nombre.capitalize()
                    self.mente_core.guardar_memoria()

        m = re.search(r"(?:quiero ser|mi meta es|mi sueño es|aspiró a)\s+([^.,;]{2,50})", t)
        if m:
            if self.mente_core:
                self.mente_core.actualizar_perfil_usuario("metas_y_sueños", m.group(1).strip())

        m = re.search(r"(?:mi color favorito es|me gusta el color)\s+([a-záéíóúñ]+)", t)
        if m:
            if self.mente_core:
                self.mente_core.actualizar_perfil_usuario("preferencias.colores", m.group(1).strip())

        if len(texto) > 25:
            self._extraer_perfil_con_llm(texto)

    def _extraer_perfil_con_llm(self, texto):
        prompt = f"""Extrae datos personales del texto en JSON. Si no hay datos, devuelve {{}}.
Campos: nombre, musica, comida, como_me_llama, metas, color_favorito, peliculas.
Texto: "{texto}"
JSON:"""
        try:
            res = ollama.generate(
                model=self.model_chat,
                prompt=prompt,
                options={"num_predict": 80, "temperature": 0.1},
                keep_alive=self.keep_alive_chat  # SOLUCIÓN #4
            )
            raw = res["response"].strip()
            if raw.startswith("`"):
                raw = raw.split("`")[1].replace("json", "").strip()
            datos = json.loads(raw)
            for k, v in datos.items():
                if v and str(v).lower() not in ["null", "none", ""]:
                    if k == "como_me_llama":
                        # Vive en Memoria.json -> relacion, no en el perfil (Configuracion.json).
                        if self.mente_core:
                            self.mente_core.memoria.setdefault("relacion", {})["como_le_dice_alex_a_nova"] = str(v).capitalize()
                            self.mente_core.guardar_memoria()
                        continue
                    key_map = {
                        "musica": "preferencias.musica",
                        "comida": "preferencias.comida",
                        "metas": "metas_y_sueños",
                        "color_favorito": "preferencias.colores",
                        "peliculas": "preferencias.peliculas_series",
                        "nombre": "nombre_preferido"
                    }
                    if self.mente_core:
                        self.mente_core.actualizar_perfil_usuario(key_map.get(k, k), str(v))
        except Exception:
            logger.exception("Excepcion silenciada en _extraer_perfil_con_llm")

    def _skill(self, nombre: str, *args, **kwargs) -> dict:
        """
        Ejecuta una habilidad fundamental de nova_skills (mouse, teclado,
        ventanas, archivos, sistema...) con manejo de errores incluido.
        Devuelve siempre {"ok", "resultado", "error"}, nunca lanza excepción.

        Preferimos pasar por self.mente_core.ejecutar_skill() cuando existe,
        porque así la misma llamada queda visible para el actuador "skill"
        del cerebro (mismo registro de salud, mismos logs); si la mente no
        está activa, caemos directo a nova_skills.SkillRegistry.
        """
        if self.mente_core:
            try:
                return self.mente_core.ejecutar_skill(nombre, *args, **kwargs)
            except Exception as e:
                logger.exception(f"[NOVA] Error ejecutando skill '{nombre}' vía mente_core: {e}")
        if NOVA_SKILLS_AVAILABLE:
            return SkillRegistry.ejecutar(nombre, *args, **kwargs)
        return {"ok": False, "resultado": None, "error": "nova_skills no disponible"}

    def ejecutar_comandos(self, texto):
        t = texto.lower().strip()

        if any(x in t for x in ["entra a", "entrar a", "métete a", "metete a", "meterte a",
                                  "ve a", "vete a", "anda a", "abre la página", "abre la pagina",
                                  "navega a", "navegar a", "métete en", "metete en"]):
            url, es_busqueda, reproduccion_directa = self._extraer_sitio_y_busqueda(texto)
            if url:
                webbrowser.open(url)
                if reproduccion_directa:
                    self.hablar("Listo, encontré uno y te lo puse a reproducir")
                elif es_busqueda:
                    self.hablar("Buscándolo ahora, dale un vistazo")
                else:
                    self.hablar(f"Abriendo {url} en navegador")
                return True
            else:
                self.hablar("¿A qué página quieres que vaya? Dime la URL.")
                return True

        if "busca en google" in t:
            q = t.split("busca en google", 1)[-1].strip()
            webbrowser.open(f"https://google.com/search?q={q.replace(' ', '+')}")
            self.hablar("Buscando en Google")
            return True

        if "busca en youtube" in t:
            q = t.split("busca en youtube", 1)[-1].strip()
            webbrowser.open(f"https://youtube.com/results?search_query={q.replace(' ', '+')}")
            self.hablar("Buscando en YouTube")
            return True

        if "diagnostico mental" in t or "como te sientes" in t or "estado mental" in t:
            if self.mente_core:
                diag = self.mente_core.obtener_diagnostico()
                print(diag)
                self.hablar(self.mente_core.mente.emociones.como_me_siento())
            else:
                self.hablar("Mi mente propia no está activa aún.")
            return True

        # ===== Volumen / multimedia (ahora vía nova_skills, con verificación
        # de errores y contabilidad de salud en vez de pyautogui directo) =====
        # Este atajo fijo es SOLO para "sube/baja el volumen" a secas (sin
        # número): un empujón relativo de 5 pasos. Si la frase trae un
        # número ("...a 80", "...al 80%"), la dejamos pasar al cerebro para
        # que use establecer_volumen() y ponga el valor EXACTO — antes esto
        # se interceptaba acá y el número se ignoraba en silencio.
        tiene_numero = any(c.isdigit() for c in t)
        if "sube el volumen" in t and not tiene_numero:
            r = self._skill("subir_volumen", 5)
            self.hablar("Volumen subido" if r["ok"] else "No pude subir el volumen")
            return True
        if "baja el volumen" in t and not tiene_numero:
            r = self._skill("bajar_volumen", 5)
            self.hablar("Volumen bajado" if r["ok"] else "No pude bajar el volumen")
            return True
        if "silencio" in t or "mute" in t:
            r = self._skill("silenciar_multimedia")
            self.hablar("Silenciado" if r["ok"] else "No pude silenciar")
            return True
        if "reproduce" in t or "pausa la música" in t or "pausa la musica" in t:
            r = self._skill("reproducir_pausar")
            self.hablar("Listo" if r["ok"] else "No pude controlar la reproducción")
            return True
        if "siguiente canción" in t or "siguiente cancion" in t or "siguiente pista" in t:
            r = self._skill("siguiente_pista")
            self.hablar("Siguiente" if r["ok"] else "No pude cambiar de pista")
            return True
        if "canción anterior" in t or "cancion anterior" in t or "pista anterior" in t:
            r = self._skill("pista_anterior")
            self.hablar("Volviendo a la anterior" if r["ok"] else "No pude cambiar de pista")
            return True

        if "abre youtube" in t:
            webbrowser.open("https://youtube.com"); self.hablar("Abriendo YouTube"); return True
        if "abre google" in t:
            webbrowser.open("https://google.com"); self.hablar("Abriendo Google"); return True

        if "captura" in t or "pantallazo" in t:
            r = self._skill("capturar_pantalla_recorte")
            self.hablar("Captura guardada" if r["ok"] else "No pude tomar la captura")
            return True

        # ===== Ventanas =====
        if "minimiza todo" in t or "minimiza las ventanas" in t or "muestra el escritorio" in t:
            r = self._skill("mostrar_escritorio")
            self.hablar("Listo" if r["ok"] else "No pude minimizar todo")
            return True
        if "maximiza la ventana" in t or "maximiza esto" in t:
            r = self._skill("maximizar_ventana")
            self.hablar("Maximizada" if r["ok"] else "No pude maximizar la ventana")
            return True
        if "minimiza la ventana" in t or "minimiza esto" in t:
            r = self._skill("minimizar_ventana")
            self.hablar("Minimizada" if r["ok"] else "No pude minimizar la ventana")
            return True
        if "cierra esta ventana" in t or "cierra la ventana" in t:
            r = self._skill("cerrar_ventana_activa")
            self.hablar("Cerrada" if r["ok"] else "No pude cerrar la ventana")
            return True
        if "cambia de ventana" in t or "alt tab" in t:
            r = self._skill("alt_tab")
            self.hablar("Listo" if r["ok"] else "No pude cambiar de ventana")
            return True

        # ===== Archivos =====
        if "organiza mi carpeta de descargas" in t or "organiza descargas" in t or "organiza mis descargas" in t:
            ruta = self._skill("obtener_ruta_descargas")
            if ruta["ok"]:
                r = self._skill("organizar_carpeta_por_tipo", ruta["resultado"])
                if r["ok"]:
                    total = sum(r["resultado"].values()) if r["resultado"] else 0
                    self.hablar(f"Listo, organicé {total} archivos de Descargas por tipo")
                else:
                    self.hablar("No pude organizar la carpeta de Descargas")
            else:
                self.hablar("No pude encontrar tu carpeta de Descargas")
            return True

        # ===== Sistema =====
        if "cuanta bateria" in t or "cuánta batería" in t or "nivel de bateria" in t or "nivel de batería" in t:
            r = self._skill("obtener_bateria")
            if r["ok"]:
                b = r["resultado"]
                estado_carga = "cargando" if b["cargando"] else "sin cargar"
                self.hablar(f"Tienes {b['porcentaje']}% de batería, {estado_carga}")
            else:
                self.hablar("No pude leer el nivel de batería, puede que este equipo no tenga")
            return True
        if "espacio en disco" in t or "cuanto espacio libre" in t or "cuánto espacio libre" in t:
            r = self._skill("obtener_espacio_disco")
            if r["ok"]:
                d = r["resultado"]
                self.hablar(f"Tienes {d['libre_gb']} gigas libres de {d['total_gb']}")
            else:
                self.hablar("No pude leer el espacio en disco")
            return True
        if "bloquea la pantalla" in t or "bloquea el equipo" in t or "bloquea la pc" in t:
            self.hablar("Bloqueando la pantalla")
            r = self._skill("bloquear_pantalla")
            if not r["ok"]:
                self.hablar("No pude bloquear la pantalla")
            return True
        if "abre la calculadora" in t or "abre calculadora" in t:
            r = self._skill("abrir_aplicacion", "calc.exe")
            self.hablar("Abriendo la calculadora" if r["ok"] else "No pude abrir la calculadora")
            return True
        if "cuantas habilidades tienes" in t or "cuántas habilidades tienes" in t or "que sabes hacer" in t or "qué sabes hacer" in t:
            if NOVA_SKILLS_AVAILABLE:
                self.hablar(f"Tengo {SkillRegistry.total()} habilidades básicas: mouse, teclado, ventanas, aplicaciones, archivos, sistema, red y más.")
            else:
                self.hablar("Ahora mismo no tengo mis habilidades básicas conectadas.")
            return True

        if any(x in t for x in ["salir", "cerrar", "adiós nova", "adios nova"]):
            self.hablar("Adiós. Nos vemos.")
            self.after(1000, self.on_close); return True
        return False


    def tomar_captura_pantalla(self):
        # ANTES: hacía su propio ImageGrab.grab() acá, un cuarto punto de
        # captura de pantalla suelto en el proyecto, además del que ya
        # corre en nova_vision.captura_compartida. Duplicaba trabajo (dos
        # capturas de la misma pantalla, en el mismo instante, por dos
        # caminos separados) y se perdía las mejoras de esa captura
        # compartida: motor GPU (dxcam) si está disponible, ritmo
        # adaptativo, etc.
        #
        # AHORA: si self.vision (NovaVision) está disponible, reusa esa
        # misma captura compartida en vez de pedir una propia. Solo cae al
        # ImageGrab.grab() directo como último recurso, si NovaVision no
        # se pudo cargar.
        if self.vision:
            try:
                img_path = self.vision.capturar(alta_resolucion=False, forzar=True)
                if img_path:
                    return img_path
            except Exception as e:
                logger.exception(f"[NOVA] Error usando vision.capturar(), cae a captura propia: {e}")

        try:
            screenshot = ImageGrab.grab()
            max_size = 1024
            w, h = screenshot.size
            if w > max_size or h > max_size:
                ratio = min(max_size / w, max_size / h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                screenshot = screenshot.resize((new_w, new_h), Image.Resampling.LANCZOS)
            temp_dir = tempfile.gettempdir()
            img_path = os.path.join(temp_dir, "nova_vision.jpg")
            screenshot.convert("RGB").save(img_path, format="JPEG", quality=60)
            return img_path
        except Exception as e:
            logger.exception(f"[NOVA] Error captura: {e}")
            return None

    def responder_llm(self, prompt):
        if self.is_processing:
            return
        self.is_processing = True
        try:
            self.mostrar_estado("pensando")
            print("[NOVA] Pensando...")
        except:
            logger.exception("Excepcion silenciada en responder_llm")

        try:
            recuerdos = []
            if self.mente_core:
                recuerdos = self.mente_core.recuperar_relevante(prompt, n=3)
            if recuerdos:
                memoria_extra = "Recuerdos relevantes de conversaciones pasadas:\n" + "\n".join(f"- {r}" for r in recuerdos)
                if self.mente_core:
                    self.historial[0]["content"] = self.mente_core.generar_contexto_sistema() + "\n" + memoria_extra
        except Exception as e:
            logger.exception(f"[NOVA] Error recuperando memoria: {e}")

        try:
            if self.mente_core:
                self.historial[0] = {"role": "system", "content": self.mente_core.generar_contexto_sistema()}
        except Exception as e:
            logger.exception(f"[NOVA] Error contexto: {e}")

        usar_vision = False
        img_path = None
        try:
            usar_vision = self.necesita_vision(prompt)
        except:
            logger.exception("Excepcion silenciada en responder_llm")

        if usar_vision:
            try:
                print("[NOVA] Observando...")
                img_path = self.tomar_captura_pantalla()
            except Exception as e:
                logger.exception(f"[NOVA] Error captura: {e}")

        modelo = self.model_chat
        if usar_vision and img_path and os.path.exists(img_path):
            modelo = self.model_vision

        print(f"[NOVA] Modelo: {modelo}")

        try:
            if img_path and os.path.exists(img_path):
                mensaje_usuario = {"role": "user", "content": prompt, "images": [img_path]}
            else:
                mensaje_usuario = {"role": "user", "content": prompt}

            self.historial.append(mensaje_usuario)

            opciones = {
                "temperature": 0.5,
                "num_predict": 220 if self.necesita_respuesta_larga(prompt) else 60,
                "num_ctx": 2048,
                "top_k": 20,
                "top_p": 0.75,
                "repeat_penalty": 1.1,
                "mirostat": 0,
                "stop": ["\n", "Usuario:", "Tú:"],
            }

            res = ollama.chat(
                model=modelo,
                messages=self.historial,
                options=opciones,
                keep_alive=self._keep_alive_para(modelo)  # SOLUCIÓN #4
            )
            msg = res["message"]["content"].strip()
            self._set_ultima_respuesta(msg)

            self.historial[-1] = {"role": "user", "content": prompt}
            self.historial.append({"role": "assistant", "content": msg})

            if len(self.historial) > 7:
                self.historial = [self.historial[0]] + self.historial[-6:]

            print(f"Nova: {msg[:100]}..." if len(msg) > 100 else f"Nova: {msg}")

            if self.mente_core:
                try:
                    self.mente_core.registrar_interaccion(prompt, msg)
                except Exception as e:
                    logger.exception(f"[NOVA] Error registro: {e}")

            if self.nova3d:
                try:
                    self.nova3d.state('speaking')
                except:
                    logger.exception("Excepcion silenciada en responder_llm")

            self.hablar(msg)

        except Exception as e:
            logger.exception(f"[NOVA] Error Ollama: {e}")
            if self.nova3d:
                try:
                    self.nova3d.state('error')
                except:
                    logger.exception("Excepcion silenciada en responder_llm")
            # BUGFIX: antes cualquier excepción acá (incluida la típica
            # ConnectionError cuando Ollama está caído) se anunciaba con el
            # mismo "Error interno. Intenta de nuevo.", sin actualizar
            # self.ollama_available — así que el siguiente intento volvía a
            # golpear la conexión y fallar de nuevo. Ahora, si es un error de
            # conexión, avisamos con un mensaje más claro y forzamos que el
            # próximo _ollama_disponible_ahora() vuelva a chequear en vez de
            # esperar el cooldown completo.
            es_error_conexion = isinstance(e, ConnectionError) or "connect" in str(e).lower()
            if es_error_conexion:
                self.ollama_available = False
                self._ultimo_check_ollama = time.time()
                self.hablar("Perdí la conexión con Ollama. Revisa que esté corriendo e inténtalo de nuevo.")
            else:
                self.hablar("Error interno. Intenta de nuevo.")

        finally:
            self.is_processing = False
            try:
                self.mostrar_estado("idle")
                print("[NOVA] Listo. Mantén 5 para hablar." if self.mic_available else "[NOVA] Sin micrófono.")
            except:
                logger.exception("Excepcion silenciada en responder_llm")
            if img_path and os.path.exists(img_path):
                try:
                    os.remove(img_path)
                except:
                    logger.exception("Excepcion silenciada en responder_llm")

    def _respuesta_ollama(self, texto_usuario: str, ocluir_historial: bool = False) -> str:
        """Genera respuesta de Ollama con capacidad de oclusión para razonamientos internos."""
        try:
            if not self._ollama_disponible_ahora():
                return "<SILENCIO>"

            if ocluir_historial:
                res = ollama.generate(
                    model=self.model_chat,
                    prompt=texto_usuario,
                    options={"temperature": 0.45, "num_predict": 70},
                    keep_alive=self.keep_alive_chat  # SOLUCIÓN #4
                )
                return res["response"].strip()

            recuerdos = []
            if self.mente_core:
                recuerdos = self.mente_core.recuperar_relevante(texto_usuario, n=2)
            memoria_extra = ""
            if recuerdos:
                memoria_extra = "Recuerdos relevantes:\n" + "\n".join(f"- {r}" for r in recuerdos)

            if self.mente_core:
                self.historial[0] = {"role": "system", "content": self.mente_core.generar_contexto_sistema() + "\n" + memoria_extra}

            self.historial.append({"role": "user", "content": texto_usuario})

            num_predict = 220 if self.necesita_respuesta_larga(texto_usuario) else 60
            res = ollama.chat(
                model=self.model_chat,
                messages=self.historial,
                options={"temperature": 0.65, "num_predict": num_predict, "num_ctx": 2048,
                         "stop": ["\n", "Usuario:", "Tú:"]},
                keep_alive=self.keep_alive_chat  # SOLUCIÓN #4
            )
            msg = res["message"]["content"].strip()

            self.historial.append({"role": "assistant", "content": msg})
            if len(self.historial) > 7:
                self.historial = [self.historial[0]] + self.historial[-6:]

            if self.mente_core:
                self.mente_core.registrar_interaccion(texto_usuario, msg)

            return msg
        except Exception as e:
            logger.exception(f"[NOVA] Error fallback Ollama: {e}")
            return "<SILENCIO>"

    def _primer_video_youtube(self, query: str, timeout: float = 4.0) -> Optional[str]:
        """
        Busca 'query' en YouTube y devuelve la URL directa
        (youtube.com/watch?v=...) del primer resultado, para que al
        abrirla en el navegador el video arranque a reproducirse solo
        (a diferencia de la página de /results, que solo lista opciones).

        Técnica sin API key: la página de resultados de YouTube trae
        embebido un bloque de JSON (ytInitialData) con el "videoId" de
        cada resultado; tomamos el primero que aparece con una regex.
        Es una técnica NO oficial — si YouTube cambia su HTML puede dejar
        de funcionar de un día para el otro. Por eso nunca debe ser la
        única vía: si esto devuelve None, el llamador tiene que caer a
        abrir la página de resultados de búsqueda normal, nunca mostrar
        un error al usuario por esto.
        """
        if not REQUESTS_AVAILABLE:
            return None
        try:
            url_busqueda = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            resp = requests.get(url_busqueda, headers=headers, timeout=timeout)
            resp.raise_for_status()
            video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
            if not video_ids:
                return None
            return f"https://www.youtube.com/watch?v={video_ids[0]}"
        except Exception as e:
            logger.debug(f"[NOVA] No pude resolver el primer video de YouTube para '{query}': {e}")
            return None

    def _extraer_sitio_y_busqueda(self, texto: str):
        """
        Para comandos tipo 'entra a youtube y busca una canción relajante' o
        'entra a youtube pero busca la canción': antes, _extraer_url() solo
        tomaba la palabra siguiente a 'entra a' (ej. 'youtube') e ignoraba
        el resto de la frase por completo — por eso Nova solo abría
        youtube.com en blanco y nunca buscaba nada, aunque el usuario lo
        haya pedido clarísimo.

        Si el sitio es youtube y hay intención de búsqueda, intenta ir un
        paso más allá de solo mostrar resultados: resuelve el primer video
        con _primer_video_youtube() y abre esa URL directamente, así el
        video arranca a reproducirse solo. Si eso falla (sin internet,
        cambió el HTML de YouTube), cae a abrir la página de resultados de
        búsqueda, que sigue siendo mucho mejor que la home en blanco de
        antes. Si el sitio es google, arma la búsqueda normal de Google.

        Devuelve (url, es_busqueda: bool, reproduccion_directa: bool).
        """
        t = texto.lower()
        m_sitio = re.search(
            r'(?:entra a|entrar a|métete a|metete a|meterte a|ve a|vete a|anda a|'
            r'abre la página|abre la pagina|navega a|navegar a|métete en|metete en)\s+(\S+)',
            t
        )
        sitio = m_sitio.group(1).strip(" .,;") if m_sitio else None

        m_busqueda = re.search(
            r'busc(?:a|ar|ame|á|alo|ala|ues|uemos)\w*\s+'
            r'(?:en el buscador(?:\s+de\s+\w+)?\s+)?'
            r'(?:una|un|la|el|algo)?\s*(.+?)(?:\s+y\s+repro\w*|\s+y\s+p[oó]n\w*|[.,;]|$)',
            t
        )
        query = m_busqueda.group(1).strip(" .,;") if m_busqueda else ""

        if sitio == "youtube" and query:
            video_url = self._primer_video_youtube(query)
            if video_url:
                return video_url, True, True
            return f"https://youtube.com/results?search_query={query.replace(' ', '+')}", True, False

        if sitio == "google" and query:
            return f"https://google.com/search?q={query.replace(' ', '+')}", True, False

        return self._extraer_url(texto), False, False

    def _extraer_url(self, texto: str):
        urls = re.findall(r'https?://[^\\s]+', texto)
        if urls:
            return urls[0]
        dominios = re.findall(
            r'(?:entra a|entrar a|métete a|metete a|meterte a|ve a|vete a|anda a|'
            r'abre la página|abre la pagina|navega a|navegar a|métete en|metete en)\s+(\S+)',
            texto.lower()
        )
        if not dominios:
            return None
        d = dominios[0].strip(" .,;")

        # Sitios comunes dichos por su nombre, sin ".com" (muy típico al hablar
        # por voz): completar al dominio real en vez de armar una URL rota.
        sitios_conocidos = {
            "google": "google.com", "youtube": "youtube.com", "gmail": "gmail.com",
            "facebook": "facebook.com", "instagram": "instagram.com", "twitter": "twitter.com",
            "x": "x.com", "wikipedia": "wikipedia.org", "amazon": "amazon.com",
            "whatsapp": "web.whatsapp.com", "netflix": "netflix.com", "spotify": "spotify.com",
            "reddit": "reddit.com", "chatgpt": "chat.openai.com",
        }
        if d in sitios_conocidos:
            d = sitios_conocidos[d]
        elif "." not in d:
            # Nombre sin dominio conocido y sin punto: mejor esfuerzo, .com
            d = f"{d}.com"

        if not d.startswith(('http://', 'https://')):
            d = 'https://' + d
        return d

    def on_close(self, force_exit=False):
        if self.closing:
            return
        self.closing = True

        print("[NOVA] Iniciando cierre graceful...")

        if self.mente_core:
            try:
                self.mente_core.detener()
            except Exception as e:
                logger.exception(f"[NOVA] Error cerrando mente: {e}")

        try:
            self.audio_engine.fade_out_global(200)
            self.audio_engine.limpiar_temporales()
        except Exception:
            logger.exception("Excepcion silenciada en on_close")

        self.ptt_active = False

        if self.nova3d:
            try:
                self.nova3d.close()
            except Exception as e:
                logger.exception(f"[NOVA] Error cerrando 3D: {e}")

        if self.hotkey_listener:
            try:
                self.hotkey_listener.stop()
            except Exception:
                logger.exception("Excepcion silenciada en on_close")

        if self.audio_pyaudio:
            try:
                self.audio_pyaudio.terminate()
            except Exception:
                logger.exception("Excepcion silenciada en on_close")

        try:
            self.destroy()
        except Exception:
            logger.exception("Excepcion silenciada en on_close")

        print("[NOVA] ✅ Cierre completado.")

        if force_exit:
            time.sleep(0.5)
            
            try:
                pid = os.getpid()
                subprocess.Popen("taskkill /PID %d /T /F" % pid, shell=True)
            except Exception:
                logger.exception("Excepcion silenciada en on_close")
            
            time.sleep(0.2)
            sys.exit(0)


if __name__ == "__main__":
    app = NovaApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("[NOVA] Interrupción detectada (Ctrl+C)...")
        app.on_close(force_exit=True)
    finally:
        print("[NOVA] Programa terminado.")