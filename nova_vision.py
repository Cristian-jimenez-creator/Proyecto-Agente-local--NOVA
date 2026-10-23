"""
nova_vision.py — Sistema de Visión Biológica y Autónoma para Nova (v2.5)
========================================================================
Incorpora: OCR, detección de templates, API nativa de Windows, inferencia 
emocional y el Filtro Sacádico de Píxeles para ahorrar recursos del PC.
"""

import os
import json
import time
import threading
import tempfile
import hashlib
import re
import logging
from datetime import datetime
from PIL import Image, ImageGrab, ImageEnhance

# numpy y cv2 se importan acá arriba (y no más abajo, junto a pyautogui,
# como en la v2.5 original) porque CapturaCompartida los usa en la firma
# de _procesar_frame_nuevo (arr: np.ndarray) y en el resize del thumbnail
# (cv2.resize). Esa clase ahora está definida antes en el archivo que el
# bloque de imports viejo, así que si np/cv2 se importaran más abajo,
# Nova rompería al arrancar con NameError apenas Python evaluara esa
# anotación de tipo al definir la clase.
import numpy as np
import cv2

# ==========================
# LOGGING
# ==========================
# En vez de tragarse las excepciones con "except: pass" o imprimirlas
# como texto genérico, se registran con logger.exception() para que
# el traceback completo quede guardado en nova_vision.log sin romper
# la ejecución del programa.
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "nova_vision.log")

logger = logging.getLogger("nova_vision")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)

    _file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(module)s:%(lineno)d | %(message)s"
    ))

    _console_handler = logging.StreamHandler()
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    logger.addHandler(_file_handler)
    logger.addHandler(_console_handler)
    logger.propagate = False

# =============================================================================
# CAPTURA DE PANTALLA — GPU-first, hilo dedicado, por eventos de cambio
# =============================================================================
# ANTES (v2.5): un solo punto de captura, pero basado en ImageGrab.grab()
# bajo demanda con caché de TTL (0.75s). Cada consumidor "pedía" pantalla y
# esperaba a que PIL la tomara (~50-150ms, bloqueante) si el TTL había
# vencido. Eso es lo que hacía que Nova "mirara" cada tanto en vez de ver
# de forma continua.
#
# AHORA: un hilo de captura dedicado, corriendo todo el tiempo a un fps
# objetivo, usando el motor más rápido disponible en esta máquina:
#   1) dxcam  -> Desktop Duplication API de DirectX (GPU). ~1-2ms/frame,
#                CPU casi en cero, hasta 60-144fps. Es la misma API que
#                usan OBS/Discord para capturar pantalla sin costo. Solo
#                Windows + GPU con drivers DX11.
#   2) mss    -> captura por GDI, 5-10x más rápido que PIL.ImageGrab.
#                Funciona en Windows/Linux/Mac, sin GPU.
#   3) PIL.ImageGrab -> fallback universal si no hay nada más instalado.
#
# El hilo compara un thumbnail barato (32x32) en cada frame para saber si
# "de verdad" cambió algo, y deja ese resultado listo en memoria. Así el
# resto de Nova nunca espera una captura: solo lee el último estado, y
# puede preguntar "¿cambió algo desde la última vez que miré?" en vez de
# comparar por su cuenta cada vez (eso es lo que antes hacía
# detectar_cambio_ligero() de forma redundante y más lenta).
try:
    import dxcam
    DXCAM_AVAILABLE = True
except ImportError:
    DXCAM_AVAILABLE = False
    logger.debug("[VISION] dxcam no disponible. Instala: pip install dxcam (Windows + GPU DX11)")

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False
    logger.debug("[VISION] mss no disponible. Instala: pip install mss")


class CapturaCompartida:
    """Punto único de captura de pantalla para todo Nova.

    Ya no es 'pedime la pantalla y te la doy si no venció el TTL'. Corre
    un hilo propio que captura continuamente al fps objetivo con el motor
    más rápido disponible (dxcam > mss > PIL), y descarta el trabajo caro
    (thumbnail diff, notificar cambio) si el frame es idéntico al anterior.

    obtener() sigue devolviendo un PIL.Image, compatible con todo el
    código viejo (ocr_pantalla, buscar_template, capturar, etc).
    obtener_si_cambio(desde_timestamp) es la API nueva, pensada para loops
    de percepción: no devuelve nada si la pantalla sigue igual, así el
    consumidor no gasta CPU reprocesando lo mismo miles de veces por
    minuto.
    """

    def __init__(self, fps_idle: float = 2.0, fps_activo: int = 30,
                 ventana_actividad: float = 2.0, umbral_cambio: float = 0.015):
        # ANTES: fps_objetivo fijo (ej. 30) corriendo todo el tiempo, sin
        # importar si el usuario está frente a la PC o no. Eso es CPU
        # constante, 24/7, incluso con la pantalla quieta durante horas.
        #
        # AHORA: captura ADAPTATIVA, como el ojo humano relajándose cuando
        # no hay estímulos:
        #   - fps_idle (bajo, ej. 2/seg): ritmo normal, mientras la pantalla
        #     no cambia. Esto es casi gratis en CPU.
        #   - fps_activo (alto, ej. 30/seg): SOLO durante 'ventana_actividad'
        #     segundos después de detectar un cambio real. Es decir, Nova
        #     "despierta" al instante apenas algo se mueve, sigue de cerca
        #     mientras dura la actividad, y se relaja sola en cuanto todo
        #     vuelve a quedar quieto.
        # El resultado: la mayor parte del día Nova gasta lo mismo que
        # respirar, y solo acelera cuando de verdad hay algo que mirar.
        self._fps_idle = fps_idle
        self._fps_activo = fps_activo
        self._ventana_actividad = ventana_actividad
        self._umbral_cambio = umbral_cambio
        self._lock = threading.Lock()
        self._ultima_imagen = None          # PIL.Image, para compatibilidad
        self._ultimo_timestamp = 0.0
        self._ultimo_cambio_timestamp = 0.0
        self._thumb_anterior = None
        self._motor = None                  # "dxcam" | "mss" | "pil"
        self._cam = None                    # instancia de dxcam si aplica
        self._sct = None                    # instancia de mss si aplica
        self._hilo = None
        self._activo = False
        self._inicializar_motor()

    def _inicializar_motor(self):
        if DXCAM_AVAILABLE:
            try:
                self._cam = dxcam.create(output_idx=0, output_color="RGB")
                self._motor = "dxcam"
                logger.info("[VISION] Captura por dxcam (Desktop Duplication API / GPU).")
                return
            except Exception:
                logger.exception("[VISION] dxcam disponible pero falló al iniciar, cae a mss/PIL")
        if MSS_AVAILABLE:
            self._motor = "mss"
            logger.info("[VISION] Captura por mss (sin GPU/DX11 disponible).")
            return
        self._motor = "pil"
        logger.info("[VISION] Captura por PIL.ImageGrab (fallback más lento, considera instalar mss o dxcam).")

    def iniciar(self):
        """Arranca el hilo de captura continua. Idempotente: si ya está
        corriendo, no hace nada."""
        if self._activo:
            return
        self._activo = True
        self._hilo = threading.Thread(target=self._loop_captura, daemon=True, name="nova-captura")
        self._hilo.start()

    def detener(self):
        self._activo = False

    def _capturar_frame_crudo(self):
        """Devuelve un array numpy RGB (H, W, 3) con el motor activo."""
        if self._motor == "dxcam":
            return self._cam.get_latest_frame()  # None si aún no hay frame
        if self._motor == "mss":
            if self._sct is None:
                self._sct = mss.mss()
            shot = self._sct.grab(self._sct.monitors[0])
            return np.array(shot)[:, :, :3][:, :, ::-1]  # BGRA -> RGB
        img = ImageGrab.grab()
        return np.array(img)

    def _loop_captura(self):
        while self._activo:
            t0 = time.time()
            try:
                arr = self._capturar_frame_crudo()
                if arr is not None:
                    self._procesar_frame_nuevo(arr)
            except Exception:
                logger.exception("Excepcion silenciada en _loop_captura")

            # Ritmo adaptativo: si hubo un cambio real hace poco (dentro de
            # 'ventana_actividad'), mantenemos fps_activo. Si la pantalla
            # lleva rato quieta, bajamos a fps_idle. Esto se recalcula en
            # cada vuelta, así que la transición "reposo -> alerta" y
            # "alerta -> reposo" es automática, sin hilos ni hooks extra.
            with self._lock:
                segundos_desde_cambio = t0 - self._ultimo_cambio_timestamp
            en_actividad = segundos_desde_cambio < self._ventana_actividad
            fps_actual = self._fps_activo if en_actividad else self._fps_idle

            periodo = 1.0 / max(0.1, fps_actual)
            dt = time.time() - t0
            time.sleep(max(0.0, periodo - dt))

    def _procesar_frame_nuevo(self, arr: np.ndarray):
        # Comparación barata (32x32) para saber si de verdad cambió algo.
        # Esto es lo que evita que el resto de Nova reprocese docenas de
        # veces por segundo una pantalla que sigue igual.
        pequeno = cv2.resize(arr, (32, 32), interpolation=cv2.INTER_NEAREST).astype(np.float32)
        hubo_cambio = True
        if self._thumb_anterior is not None:
            diff = np.mean(np.abs(pequeno - self._thumb_anterior)) / 255.0
            hubo_cambio = diff > self._umbral_cambio
        self._thumb_anterior = pequeno

        img = Image.fromarray(arr)
        ahora = time.time()
        with self._lock:
            self._ultima_imagen = img
            self._ultimo_timestamp = ahora
            if hubo_cambio:
                self._ultimo_cambio_timestamp = ahora

    # ---- API pública -----------------------------------------------------
    def obtener(self, forzar: bool = False):
        """Compatibilidad con el código existente: devuelve el último
        PIL.Image disponible. Si el hilo de captura todavía no arrancó (o
        el motor falló), captura una vez al vuelo como antes.

        forzar=True fuerza una captura nueva en este instante, en vez de
        devolver la que ya estaba en caché (hasta fps_idle de antigüedad).
        Pensado para pedidos explícitos del usuario ('mira la pantalla'),
        donde importa más la frescura exacta que ahorrar una captura."""
        if not forzar:
            with self._lock:
                if self._ultima_imagen is not None:
                    return self._ultima_imagen
        try:
            arr = self._capturar_frame_crudo()
            if arr is not None:
                img = Image.fromarray(arr)
                with self._lock:
                    self._ultima_imagen = img
                    self._ultimo_timestamp = time.time()
                return img
        except Exception:
            logger.exception("Excepcion silenciada en CapturaCompartida.obtener")
        # Si forzar=True falló la captura nueva, devolvemos la última
        # válida que tengamos en vez de None.
        with self._lock:
            return self._ultima_imagen

    def obtener_si_cambio(self, desde_timestamp: float):
        """Pensado para loops de percepción: devuelve (imagen, timestamp)
        SOLO si hubo un cambio real de pantalla después de
        'desde_timestamp'. Si no, devuelve (None, desde_timestamp) sin que
        el que llama tenga que gastar CPU comparando nada por su cuenta."""
        with self._lock:
            if self._ultimo_cambio_timestamp > desde_timestamp and self._ultima_imagen is not None:
                return self._ultima_imagen, self._ultimo_cambio_timestamp
            return None, desde_timestamp

    def motor_activo(self) -> str:
        return self._motor or "desconocido"


# Instancia única a nivel de módulo: todo el sistema (visión, núcleo
# cognitivo, scheduler de percepción) importa y usa esta misma captura en
# vez de llamar a ImageGrab.grab()/mss/dxcam directamente. El hilo de
# captura se arranca de forma perezosa (ver NovaVision.vincular_mente) para
# no gastar GPU/CPU si el "ojo" de Nova todavía no está conectado a nada.
captura_compartida = CapturaCompartida(fps_idle=2.0, fps_activo=30, ventana_actividad=2.0)

# Intentar importar motores de OCR
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    logger.debug("[VISION] EasyOCR no disponible. Instala: pip install easyocr")

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

# API nativa de Windows para lectura de controles
try:
    import uiautomation as uia
    UIA_AVAILABLE = True
except ImportError:
    UIA_AVAILABLE = False
    logger.debug("[VISION] uiautomation no disponible. Instala: pip install uiautomation")

try:
    import pywinauto
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False

import pyautogui


# =============================================================================
# 1. ESTADO EMOCIONAL DEL USUARIO (Inferencia desde señales visuales)
# =============================================================================

class EstadoUsuarioInferido:
    """Modelo del estado emocional del usuario inferido desde señales visuales."""
    def __init__(self):
        self.energia = 0.5
        self.estres = 0.0
        self.enfoque = 0.5
        self.frustracion = 0.0
        self.senales_detectadas = []
        self.app_activa = ""
        self.timestamp = 0.0

    def to_dict(self):
        return {
            "energia": round(self.energia, 2),
            "estres": round(self.estres, 2),
            "enfoque": round(self.enfoque, 2),
            "frustracion": round(self.frustracion, 2),
            "senales": self.senales_detectadas,
            "app_activa": self.app_activa,
            "timestamp": self.timestamp
        }


class InferidorEstadoUsuario:
    """Analiza señales visuales/ambientales para inferir el estado emocional del usuario."""
    def __init__(self):
        self._ultimo_estado = EstadoUsuarioInferido()
        self._historial_apps = []
        self._ultimo_cambio_app = 0.0
        self._contador_cambios_ventana = 0
        self._ultimo_reset_contador = time.time()

    def analizar(self, info_pantalla: dict, textos_ocr: list,
                 ventanas: list, emocion_nova: str) -> EstadoUsuarioInferido:
        estado = EstadoUsuarioInferido()
        estado.timestamp = time.time()
        estado.app_activa = info_pantalla.get("app_activa", "")
        senales = []

        ahora = time.time()
        if ahora - self._ultimo_reset_contador > 60:
            self._contador_cambios_ventana = 0
            self._ultimo_reset_contador = ahora

        app_actual = estado.app_activa
        if self._historial_apps and self._historial_apps[-1][1] != app_actual:
            self._contador_cambios_ventana += 1
            self._ultimo_cambio_app = ahora

        self._historial_apps.append((ahora, app_actual))
        if len(self._historial_apps) > 20:
            self._historial_apps = self._historial_apps[-20:]

        if self._contador_cambios_ventana > 5:
            estado.estres = min(1.0, estado.estres + 0.4)
            senales.append(f"Cambio_rapido_ventanas:{self._contador_cambios_ventana}")
        elif self._contador_cambios_ventana > 3:
            estado.estres = min(1.0, estado.estres + 0.2)
            senales.append(f"Cambio_moderado_ventanas:{self._contador_cambios_ventana}")

        num_ventanas = len(ventanas)
        if num_ventanas > 10:
            estado.estres = min(1.0, estado.estres + 0.25)
            estado.enfoque = max(0.0, estado.enfoque - 0.2)
            senales.append(f"Sobrecarga_ventanas:{num_ventanas}")
        elif num_ventanas > 6:
            estado.estres = min(1.0, estado.estres + 0.1)
            senales.append(f"Muchas_ventanas:{num_ventanas}")

        for v in ventanas:
            nombre = v.get("nombre", "").lower()
            if any(x in nombre for x in ["error", "fallo", "critico", "warning", "alerta"]):
                estado.frustracion = min(1.0, estado.frustracion + 0.5)
                estado.estres = min(1.0, estado.estres + 0.3)
                senales.append(f"Dialogo_error:{v.get('nombre', '')}")

        textos_combinados = " ".join([t.get("texto", "").lower() for t in textos_ocr])
        palabras_frustracion = ["no funciona", "error", "fallo", "timeout", "perdido",
                                "borrado", "no guardo", "crash", "congelado"]
        for palabra in palabras_frustracion:
            if palabra in textos_combinados:
                estado.frustracion = min(1.0, estado.frustracion + 0.3)
                senales.append(f"Texto_frustracion:{palabra}")

        tiempo_en_app = self._tiempo_en_app_actual()
        apps_creativas = ["photoshop", "blender", "gimp", "illustrator", "vs code",
                          "visual studio", "intellij", "pycharm", "unity", "obsidian"]
        apps_productivas = ["excel", "word", "powerpoint", "outlook", "chrome", "edge"]

        if tiempo_en_app > 600:
            if any(a in app_actual.lower() for a in apps_creativas):
                estado.enfoque = min(1.0, estado.enfoque + 0.15)
                senales.append(f"Largo_tiempo_creativa:{app_actual}:{tiempo_en_app}s")
            elif any(a in app_actual.lower() for a in apps_productivas):
                estado.enfoque = min(1.0, estado.enfoque + 0.1)
                senales.append(f"Largo_tiempo_productiva:{app_actual}:{tiempo_en_app}s")

        apps_descanso = ["spotify", "youtube", "netflix", "meditacion", "calm", "headspace"]
        if any(a in app_actual.lower() for a in apps_descanso):
            estado.energia = max(0.0, estado.energia - 0.1)
            estado.estres = max(0.0, estado.estres - 0.15)
            senales.append(f"App_descanso:{app_actual}")

        hora = datetime.now().hour
        if 6 <= hora < 10:
            estado.energia = min(1.0, estado.energia + 0.1)
        elif 14 <= hora < 16:
            estado.energia = max(0.0, estado.energia - 0.15)
            senales.append("Hora_baja_energia:14-16")
        elif hora >= 22 or hora < 2:
            estado.energia = max(0.0, estado.energia - 0.2)
            senales.append("Hora_nocturna")

        estado.energia = self._suavizar(self._ultimo_estado.energia, estado.energia, 0.3)
        estado.estres = self._suavizar(self._ultimo_estado.estres, estado.estres, 0.4)
        estado.enfoque = self._suavizar(self._ultimo_estado.enfoque, estado.enfoque, 0.3)
        estado.frustracion = self._suavizar(self._ultimo_estado.frustracion, estado.frustracion, 0.5)

        estado.senales_detectadas = senales
        self._ultimo_estado = estado

        return estado

    def _tiempo_en_app_actual(self) -> float:
        if not self._historial_apps: return 0.0
        app_actual = self._historial_apps[-1][1]
        for ts, app in reversed(self._historial_apps):
            if app != app_actual:
                return time.time() - ts
        return time.time() - self._historial_apps[0][0]

    @staticmethod
    def _suavizar(anterior: float, nuevo: float, factor: float) -> float:
        return anterior * (1 - factor) + nuevo * factor


# =============================================================================
# 2. ADAPTADOR DE PERCEPCIÓN ÓPTICA (Conectado a MenteCore)
# =============================================================================

class AdaptadorPercepcionVisual:
    """Traduce la visión de Nova en estímulos neurológicos para su MenteCore."""

    RUIDO_OCR = {
        "inicio", "es", "la", "el", "de", "ok", "cancelar", "aceptar",
        "file", "edit", "view", "help", "tools", "window", "00", "01",
        "am", "pm", "lunes", "martes", "miercoles", "jueves", "viernes",
        "buscar", "search", "type here to search", "escribe aquí",
        "minimizar", "maximizar", "cerrar", "x", "+"
    }

    def __init__(self, vision_instance):
        self.vision = vision_instance
        self.mente = None # Se inyectará dinámicamente desde nova_asistente
        self.inferidor = InferidorEstadoUsuario()
        self._ultimo_contexto = None
        self._ultimo_escaneo = 0.0
        self._frecuencia_escaneo = 3.5 # Techo: cada cuánto, como MÁXIMO, se
        # procesa el resto del pipeline (OCR/UIA/emitir percepción a la
        # mente), para no saturarla. La CAPTURA en sí ya no depende de esto:
        # corre aparte en captura_compartida con ritmo adaptativo (fps bajo
        # en reposo, ráfaga corta tras un cambio real), así que un cambio
        # de pantalla se detecta casi al instante aunque el "pensar sobre
        # lo que vio" siga limitado a este ritmo.
        self._ultimo_ts_frame_visto = 0.0

    def escanear_y_percibir(self, forzar: bool = False):
        ahora = time.time()
        if not forzar and (ahora - self._ultimo_escaneo) < self._frecuencia_escaneo:
            return
        self._ultimo_escaneo = ahora

        try:
            # ★ FILTRO SACÁDICO BIOLÓGICO (Ahorro de CPU del PC) ★
            # Paso 1: Leemos el título de la ventana y el mouse por API de Windows (0.001s)
            info_rapida = self.vision.obtener_info_rapida_sacadica()
            app_activa = info_rapida["app_activa"]

            # Paso 2: en vez de comparar un thumbnail nosotros mismos (como
            # antes), le preguntamos al hilo de captura -que corre aparte,
            # hasta a 30fps- si detectó un cambio real desde la última vez
            # que este loop miró. Es prácticamente gratis (una lectura con
            # lock) porque el trabajo pesado ya lo hizo ese hilo.
            frame, ts_frame = captura_compartida.obtener_si_cambio(self._ultimo_ts_frame_visto)
            hubo_cambio_pixel = frame is not None
            if hubo_cambio_pixel:
                self._ultimo_ts_frame_visto = ts_frame

            if not forzar and self._ultimo_contexto and self._ultimo_contexto["app_activa"] == app_activa:
                if not hubo_cambio_pixel:
                    return # Pantalla estática de verdad. Ojo en reposo, no lanzamos OCR.

            # Paso 3: Atención Plena. Solo llegamos aquí si la pantalla realmente cambió.
            info = self.vision.obtener_info_pantalla()
            ventanas = info.get("ventanas", [])
            mouse_pos = info.get("mouse", (0, 0))
            resolucion = info.get("resolucion", (1920, 1080))

            # SOLUCIÓN #3: el OCR completo (el paso más caro de todo el escaneo)
            # solo corre aquí si el usuario lo activó explícitamente
            # (vision.ocr_en_bucle_autonomo = True). Por defecto queda apagado
            # para no competir por CPU/GPU con Ollama en cada ciclo de 3.5s.
            if self.vision.easyocr_reader and self.vision.ocr_en_bucle_autonomo:
                textos_ocr = self.vision.ocr_pantalla()
            else:
                textos_ocr = []
            textos_relevantes = self._filtrar_texto_relevante(textos_ocr)

            estado_usuario = self.inferidor.analizar(info, textos_ocr, ventanas, "NEUTRAL")

            contexto_actual = {
                "app_activa": app_activa,
                "num_ventanas": len(ventanas),
                "mouse_region": self._region_mouse(mouse_pos, resolucion),
                "estres_usuario": estado_usuario.estres,
                "frustracion_usuario": estado_usuario.frustracion
            }

            if self._contexto_cambio_significativo(self._ultimo_contexto, contexto_actual):
                if self.mente:
                    self.mente.percibir(
                        tipo="contexto_escritorio",
                        contenido=f"App activa: {app_activa}. Ventanas: {len(ventanas)}. Estrés inferido: {estado_usuario.estres:.1f}",
                        intensidad=0.5 + (estado_usuario.estres * 0.3),
                        metadata={
                            "app_activa": app_activa,
                            "ventanas": [v.get("nombre", "") for v in ventanas[:5]],
                            "estado_usuario": estado_usuario.to_dict(),
                            "resolucion": str(resolucion)
                        }
                    )
                self._ultimo_contexto = contexto_actual

            # Percibir textos clave en pantalla
            for t in textos_relevantes:
                if self.mente:
                    self.mente.percibir(
                        tipo="texto_en_pantalla",
                        contenido=t["texto"],
                        intensidad=t["confianza"] * 0.7,
                        metadata={"coordenadas": (t["x"], t["y"]), "app": app_activa}
                    )

            # Reaccionar a cuadros de diálogo de error o peligro
            alertas = self._detectar_alertas(ventanas, textos_ocr)
            for alerta in alertas:
                if self.mente:
                    self.mente.percibir(
                        tipo="alerta_ui",
                        contenido=alerta["mensaje"],
                        intensidad=alerta["prioridad"],
                        metadata={"tipo_alerta": alerta["tipo"], "app": app_activa}
                    )

        except Exception as e:
            logger.exception("Excepcion silenciada en escanear_y_percibir") # Silencio de lectura de fondo

    def _filtrar_texto_relevante(self, textos: list) -> list:
        relevantes = []
        for t in textos:
            texto = t.get("texto", "").strip()
            if len(texto) < 2 or texto.lower() in self.RUIDO_OCR or (texto.isdigit() and len(texto) <= 4):
                continue
            relevantes.append(t)
        return relevantes

    def _region_mouse(self, mouse_pos: tuple, resolucion: tuple) -> str:
        if not resolucion or resolucion[0] == 0: return "centro"
        x, y = mouse_pos; w, h = resolucion
        cx, cy = w / 2, h / 2
        rx = "izq" if x < cx * 0.7 else "der" if x > cx * 1.3 else "centro"
        ry = "arriba" if y < cy * 0.7 else "abajo" if y > cy * 1.3 else "centro"
        return f"{ry}-{rx}"

    def _contexto_cambio_significativo(self, anterior: dict, actual: dict) -> bool:
        if anterior is None: return True
        if anterior.get("app_activa") != actual.get("app_activa"): return True
        if abs(anterior.get("estres_usuario", 0) - actual.get("estres_usuario", 0)) > 0.3: return True
        return False

    def _detectar_alertas(self, ventanas: list, textos_ocr: list) -> list:
        alertas = []
        for v in ventanas:
            if "error" in v.get("nombre", "").lower():
                alertas.append({
                    "tipo": "error_ventana",
                    "mensaje": f"Diálogo de error: {v.get('nombre', '')}",
                    "prioridad": 0.95
                })
        return alertas


# =============================================================================
# 3. NOVA VISION CORE (Maneja su propio hilo autónomo)
# =============================================================================

class NovaVision:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.memoria_visual_path = os.path.join(self.base_dir, "nova_memoria_visual.json")
        self.templates_dir = os.path.join(self.base_dir, "nova_templates")

        os.makedirs(self.templates_dir, exist_ok=True)
        self.memoria = self._cargar_memoria()

        self.easyocr_reader = None
        if EASYOCR_AVAILABLE:
            # SOLUCIÓN #3: si hay GPU NVIDIA disponible, úsala para EasyOCR.
            # Antes siempre forzaba gpu=False y corría OCR entero en CPU,
            # compitiendo por núcleos con Ollama y el resto de hilos de Nova.
            usar_gpu = self._hay_gpu_disponible()
            try:
                self.easyocr_reader = easyocr.Reader(['es'], gpu=usar_gpu)
                print(f"[VISION] EasyOCR biológico listo (gpu={usar_gpu}).")
            except Exception as e:
                # Si falla con GPU (drivers/CUDA no disponibles), reintenta en CPU.
                if usar_gpu:
                    try:
                        self.easyocr_reader = easyocr.Reader(['es'], gpu=False)
                        print("[VISION] EasyOCR biológico listo (fallback a CPU).")
                    except Exception:
                        logger.exception("[VISION] Error EasyOCR (fallback CPU)")
                else:
                    logger.exception(f"[VISION] Error EasyOCR: {e}")

        # SOLUCIÓN #3: el OCR (pesado) ya NO corre en cada ciclo del bucle
        # autónomo. Por defecto está apagado ahí; solo se ejecuta bajo demanda
        # (cuando algo del sistema llama a ocr_pantalla()/buscar_texto() de
        # forma explícita) o si el usuario decide reactivarlo.
        self.ocr_en_bucle_autonomo = False

        self.resolucion_captura = 1024
        self.ultima_captura = None
        self.ultima_captura_path = None
        self._thumb_anterior = None

        # Instanciamos su nervio óptico
        self.adaptador = AdaptadorPercepcionVisual(self)
        self._hilo_retina = None
        self._ojo_activo = False

    def _hay_gpu_disponible(self) -> bool:
        """Detecta si hay una GPU NVIDIA utilizable por EasyOCR (via torch/CUDA)."""
        try:
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            return False

    def _cargar_memoria(self):
        if os.path.exists(self.memoria_visual_path):
            try:
                with open(self.memoria_visual_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: logger.exception("Excepcion silenciada en _cargar_memoria")
        return {"elementos_conocidos": {}, "apps_abiertas": {}, "historial_capturas": [], "templates_registrados": []}

    def _guardar_memoria(self):
        try:
            with open(self.memoria_visual_path, 'w', encoding='utf-8') as f:
                json.dump(self.memoria, f, ensure_ascii=False, indent=2)
        except: logger.exception("Excepcion silenciada en _guardar_memoria")

    # ========== PUENTE NEUROLÓGICO CON MENTECORE ==========
    def vincular_mente(self, mente_adapter_instance):
        """Hook biológico: Conecta la corteza visual al lóbulo frontal de Nova."""
        self.adaptador.mente = mente_adapter_instance
        # Arranca el hilo de captura continua (retina) por separado del
        # hilo de percepción (corteza). La retina captura sin parar al fps
        # objetivo; la corteza decide, a su propio ritmo, qué de eso vale
        # la pena "pensar".
        captura_compartida.iniciar()
        if not self._ojo_activo:
            self._ojo_activo = True
            self._hilo_retina = threading.Thread(target=self._bucle_retina_autonoma, daemon=True)
            self._hilo_retina.start()
            print(f"[VISION 👁️] Nervio óptico conectado (motor de captura: {captura_compartida.motor_activo()}). "
                  f"Ojo autónomo escaneando en segundo plano.")

    def _bucle_retina_autonoma(self):
        while self._ojo_activo:
            try:
                self.adaptador.escanear_y_percibir()
            except: logger.exception("Excepcion silenciada en _bucle_retina_autonoma")
            time.sleep(self.adaptador._frecuencia_escaneo)

    def escanear_y_percibir(self, forzar=False):
        """Permite que el PercepcionScheduler de la mente solicite un vistazo manual."""
        self.adaptador.escanear_y_percibir(forzar=forzar)

    # ========== FILTROS SACÁDICOS (Optimizadores de hardware) ==========
    def obtener_info_rapida_sacadica(self) -> dict:
        """Lee la app activa por API de Windows sin procesar píxeles."""
        app = "desconocido"
        if UIA_AVAILABLE:
            try:
                fg = uia.GetForegroundControl()
                if fg: app = fg.Name
            except: logger.exception("Excepcion silenciada en obtener_info_rapida_sacadica")
        return {"app_activa": app or "escritorio", "mouse": pyautogui.position()}

    def detectar_cambio_ligero(self, umbral=0.04) -> bool:
        """Se mantiene por compatibilidad con código externo que la llame
        directamente. El detector 'de verdad' ahora vive dentro del hilo
        de captura (captura_compartida), que compara cada frame contra el
        anterior de forma continua y mucho más barata que hacerlo acá bajo
        demanda. Esta versión solo hace un chequeo puntual equivalente."""
        try:
            img = captura_compartida.obtener().resize((64, 64), Image.Resampling.NEAREST)
            arr = np.array(img, dtype=np.float32)
            if self._thumb_anterior is None:
                self._thumb_anterior = arr; return True
            diff = np.mean(np.abs(self._thumb_anterior - arr)) / 255.0
            self._thumb_anterior = arr
            return diff > umbral
        except: return True

    # ========== CAPTURA DE PANTALLA ESTÁNDAR ==========
    def capturar(self, region=None, alta_resolucion=False, forzar=False):
        try:
            if region:
                x, y, w, h = region; screenshot = ImageGrab.grab(bbox=(x, y, x+w, y+h))
            else:
                # SOLUCIÓN #2: reutiliza la captura compartida para pantalla completa.
                # forzar=True (pedidos explícitos del usuario) pide un frame
                # nuevo en el instante en vez del último cacheado.
                screenshot = captura_compartida.obtener(forzar=forzar)

            self.ultima_captura = screenshot.copy()

            if not alta_resolucion:
                max_size = self.resolucion_captura
                w, h = screenshot.size
                if w > max_size or h > max_size:
                    ratio = min(max_size / w, max_size / h)
                    screenshot = screenshot.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)

            temp_dir = tempfile.gettempdir()
            img_path = os.path.join(temp_dir, f"nova_vision_{int(time.time())}.jpg")
            screenshot.convert("RGB").save(img_path, format="JPEG", quality=75)
            self.ultima_captura_path = img_path
            return img_path
        except: return None

    def capturar_region(self, x, y, w, h): return self.capturar(region=(x, y, w, h))

    # ========== OCR Y BÚSQUEDA ==========
    def ocr_pantalla(self, region=None, metodo="auto"):
        if not self.easyocr_reader: return []
        try:
            # SOLUCIÓN #2: pantalla completa sale de la caché compartida, no de un grab propio.
            img = ImageGrab.grab(bbox=region) if region else (self.ultima_captura or captura_compartida.obtener())
            resultados = []
            for (bbox, text, conf) in self.easyocr_reader.readtext(np.array(img)):
                if conf > 0.35:
                    resultados.append({
                        "texto": text.strip(),
                        "x": int(bbox[0][0]), "y": int(bbox[0][1]),
                        "w": int(bbox[2][0] - bbox[0][0]), "h": int(bbox[2][1] - bbox[0][1]),
                        "confianza": float(conf), "metodo": "easyocr"
                    })
            return resultados
        except: return []

    def buscar_texto(self, texto_buscar, region=None, tolerancia=0.8):
        resultados = self.ocr_pantalla(region=region)
        texto_buscar = texto_buscar.lower().strip()
        coincidencias = [r for r in resultados if texto_buscar in r["texto"].lower() or self._similitud(texto_buscar, r["texto"].lower()) > tolerancia]
        coincidencias.sort(key=lambda x: x["confianza"], reverse=True); return coincidencias

    def _similitud(self, a, b):
        sa = set(a.split()); sb = set(b.split())
        return len(sa & sb) / len(sa | sb) if sa and sb else 0.0

    # ========== TEMPLATES Y UIA ==========
    def guardar_template(self, nombre, region=None):
        try:
            img = ImageGrab.grab(bbox=(region[0], region[1], region[0]+region[2], region[1]+region[3])) if region else ImageGrab.grab()
            path = os.path.join(self.templates_dir, f"{nombre}.png"); img.save(path)
            self.memoria["templates_registrados"].append(nombre); self._guardar_memoria()
            return path
        except: return None

    def buscar_template(self, nombre, confidence=0.8):
        path = os.path.join(self.templates_dir, f"{nombre}.png")
        if not os.path.exists(path): return None
        try:
            # SOLUCIÓN #2: pantalla completa desde la caché compartida.
            res = cv2.matchTemplate(cv2.cvtColor(np.array(captura_compartida.obtener()), cv2.COLOR_RGB2GRAY), cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= confidence: return (int(max_loc[0]), int(max_loc[1]), cv2.imread(path).shape[1], cv2.imread(path).shape[0])
            return None
        except: return None

    def listar_ventanas_uia(self):
        if not UIA_AVAILABLE: return []
        try: return [{"nombre": w.Name, "clase": w.ClassName} for w in uia.GetRootControl().GetChildren() if w.ControlType == uia.ControlType.WindowControl and w.IsVisible]
        except: return []

    def encontrar_elemento_uia(self, nombre=None, tipo=None):
        if not UIA_AVAILABLE or not nombre: return None
        try:
            for c in uia.GetForegroundControl().GetChildren():
                if nombre.lower() not in c.Name.lower():
                    continue
                if tipo and tipo.lower() not in str(c.ControlTypeName).lower():
                    continue
                return {"nombre": c.Name, "x": c.BoundingRectangle.left, "y": c.BoundingRectangle.top}
        except: logger.exception("Excepcion silenciada en encontrar_elemento_uia")
        return None

    def click_elemento_uia(self, nombre=None, tipo=None):
        e = self.encontrar_elemento_uia(nombre, tipo=tipo)
        if e: pyautogui.click(e["x"] + 10, e["y"] + 10); return True
        return False

    def recordar_elemento(self, nombre, x, y, w=0, h=0, confianza=1.0):
        self.memoria["elementos_conocidos"][nombre] = {"x": int(x), "y": int(y), "w": int(w), "h": int(h), "ultima_vez": datetime.now().isoformat(), "confianza": confianza}
        self._guardar_memoria()

    def obtener_elemento_recordado(self, nombre): return self.memoria["elementos_conocidos"].get(nombre)

    def preprocesar_para_vision(self, img_path): return img_path

    def detectar_cambios(self, umbral=0.1): return True

    def encontrar_y_click(self, texto=None, template=None, nombre_uia=None, usar_memoria=True):
        if usar_memoria and texto and self.obtener_elemento_recordado(texto):
            e = self.obtener_elemento_recordado(texto)
            pyautogui.click(e["x"] + e["w"]//2, e["y"] + e["h"]//2); return True
        if texto and self.buscar_texto(texto):
            m = self.buscar_texto(texto)[0]; pyautogui.click(m["x"] + m["w"]//2, m["y"] + m["h"]//2)
            self.recordar_elemento(texto, m["x"], m["y"], m["w"], m["h"], m["confianza"]); return True
        return False

    def obtener_info_pantalla(self):
        return {
            "resolucion": pyautogui.size(), "mouse": pyautogui.position(),
            "ventanas": self.listar_ventanas_uia() if UIA_AVAILABLE else [],
            "app_activa": self.obtener_info_rapida_sacadica()["app_activa"]
        }


# Mantenemos el alias por si algún script externo de tu proyecto llama a la clase antigua
NovaVisionIntegrada = NovaVision