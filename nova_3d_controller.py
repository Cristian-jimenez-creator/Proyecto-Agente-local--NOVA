"""
Nova 3D Controller v0.1 — Cierre total: modelo 3D + proceso principal + terminal
procesos muy faciles de cerrar, sin dejar procesos colgados.

"""
import os
import sys
import threading
import multiprocessing
import http.server
import socketserver
import functools
import re

# --- SOLUCIÓN DPI ---
# Evita que PyQt6 intente forzar el escalado de DPI en Windows, eliminando el error de "Acceso denegado"
os.environ["QT_QPA_PLATFORM"] = "windows:dpiawareness=0"

# AÑADE ESTA LÍNEA PARA SILENCIAR LA ADVERTENCIA EN LA TERMINAL:
os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"

# --- DIAGNÓSTICO / MITIGACIÓN: contención de VRAM con Ollama ---
# El cuerpo 3D (Qt6WebEngineCore, o sea Chromium) usa la GPU para renderizar
# el modelo VRM con Three.js — la MISMA GPU (6GB de VRAM) donde Ollama tiene
# cargados los modelos de lenguaje. Confirmamos con el Visor de Eventos un
# crash 0xc0000005 (violación de acceso) en Qt6WebEngineCore.dll, y subir la
# RAM del SISTEMA de 16 a 32GB no lo solucionó — señal de que el cuello de
# botella real es la VRAM (que no cambió), no la RAM.
#
# Con FORZAR_RENDERIZADO_SOFTWARE = True, el cuerpo 3D deja de pelear por
# VRAM: Chromium renderiza por software (CPU), más lento y menos fluido
# visualmente, pero sin tocar la GPU en absoluto. Es un experimento de
# diagnóstico tanto como una mitigación: si con esto en True el 3D deja de
# caerse, confirma que el problema era contención de GPU/VRAM con Ollama.
# Poné False para volver a intentar con GPU (más fluido, pero es lo que
# venía crasheando).
# RESULTADO DEL PRIMER INTENTO: solo "--disable-gpu" apagó la GPU pero NO le
# dijo a Chromium que usara un renderizador de software como reemplazo —
# WebGL directamente no pudo crear contexto y el 3D quedó en blanco. Aun
# así, en esa sesión no volvió a aparecer el crash de violación de acceso
# ni una vez, así que la pista de VRAM seguía siendo válida.
#
# Flags corregidos (confirmados en la doc oficial de Chromium sobre
# SwiftShader): "--use-gl=angle --use-angle=swiftshader-webgl" le pide a
# Chromium que renderice WebGL específicamente vía SwiftShader (CPU/RAM,
# nada de VRAM) en vez de simplemente apagar la GPU sin reemplazo.
# "--enable-unsafe-swiftshader" hace falta porque el fallback automático a
# SwiftShader está deprecado en Chromium reciente y si no se pide
# explícito, WebGL directamente falla en vez de caer a software (que es
# justo lo que nos pasó la primera vez). "--disable-gpu-compositing" evita
# que el resto de la página también le pida VRAM al compositor.
FORZAR_RENDERIZADO_SOFTWARE = True
if FORZAR_RENDERIZADO_SOFTWARE:
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--use-gl=angle --use-angle=swiftshader-webgl --enable-unsafe-swiftshader --disable-gpu-compositing"
    )
    print("[NOVA3D] ⚙️ WebGL forzado a SwiftShader (CPU/RAM en vez de VRAM) — el 3D va a verse menos fluido, a cambio de no pelear por VRAM con Ollama.")


def _qt_process(width, height, x, y, base_dir, cmd_queue, resp_queue):
    import random

    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QMenu, QInputDialog,
        QDialog, QTextEdit, QPushButton, QListWidget, QFileDialog, QLabel
    )
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
    from PyQt6.QtCore import Qt, QUrl, QTimer, QPoint, QPropertyAnimation, QEasingCurve, QRect
    from PyQt6.QtGui import QCursor, QColor, QAction

    def start_server():
        os.chdir(base_dir)

        class SilentHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def end_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                super().end_headers()

            def guess_type(self, path):
                ext = os.path.splitext(path)[1].lower()
                if ext in ('.js', '.mjs'):
                    return 'application/javascript; charset=utf-8'
                if ext == '.json':
                    return 'application/json; charset=utf-8'
                if ext == '.wasm':
                    return 'application/wasm'
                if ext == '.vrm':
                    return 'application/octet-stream'
                return super().guess_type(path)

        socketserver.TCPServer.allow_reuse_address = True
        httpd = None
        port = None
        for p in range(8765, 8775):
            try:
                httpd = socketserver.TCPServer(("", p), SilentHandler)
                port = p
                break
            except OSError:
                continue
        if port is None:
            httpd = socketserver.TCPServer(("", 0), SilentHandler)
            port = httpd.server_address[1]

        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        print(f"[NOVA3D] 🌐 Servidor local: http://localhost:{port}")
        return httpd, port

    httpd, port = start_server()
    url = f"http://localhost:{port}/Nova3D/index.html"

    app = QApplication(sys.argv)

    window = QWidget()
    window.setWindowFlags(
        Qt.WindowType.FramelessWindowHint |
        Qt.WindowType.WindowStaysOnTopHint |
        Qt.WindowType.Tool |
        Qt.WindowType.WindowDoesNotAcceptFocus
    )
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    window.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
    window.resize(width, height)
    window.move(x, y)

    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    view = QWebEngineView()
    view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    view.setStyleSheet("background: transparent; border: none;")
    view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    profile = QWebEngineProfile("nova3d", view)
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)

    page = QWebEnginePage(profile, view)
    page.setBackgroundColor(QColor(0, 0, 0, 0))

    settings = page.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)

    view.setPage(page)
    view.setUrl(QUrl(url))
    layout.addWidget(view, 1)

    ready = False
    destroyed = False
    free_mode = True
    locked = False
    mic_active = False
    tts_muted = False
    dnd_active = False  # "No molestar": reflejo local del estado real, que vive en nova_mente_core
    current_size_idx = 1
    SIZES = [(240, 320), (320, 440), (400, 560), (500, 700)]

    free_target = QPoint(x, y)
    free_anim = None

    def pick_new_target():
        screen = app.primaryScreen().geometry()
        margin = 80
        max_dx = 60
        max_dy = 40
        current = window.pos()
        return QPoint(
            max(margin, min(screen.width() - window.width() - margin,
                current.x() + random.randint(-max_dx, max_dx))),
            max(margin, min(screen.height() - window.height() - margin,
                current.y() + random.randint(-max_dy, max_dy)))
        )

    def start_free_movement():
        nonlocal free_target, free_anim
        if not free_mode or locked or destroyed:
            return

        free_target = pick_new_target()
        duration = random.randint(3000, 8000)

        free_anim = QPropertyAnimation(window, b"pos")
        free_anim.setDuration(duration)
        free_anim.setStartValue(window.pos())
        free_anim.setEndValue(free_target)
        free_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def on_finish():
            if free_mode and not locked and not destroyed:
                QTimer.singleShot(random.randint(1000, 4000), start_free_movement)

        free_anim.finished.connect(on_finish)
        free_anim.start()

        page.runJavaScript("if(typeof setState==='function') setState('idle')")

    def stop_free_movement():
        nonlocal free_anim
        if free_anim and free_anim.state() == QPropertyAnimation.State.Running:
            free_anim.stop()
            free_anim = None

    class DragState:
        dragging = False
        offset = None

    def on_press(event):
        if event.button() == Qt.MouseButton.LeftButton:
            DragState.dragging = True
            DragState.offset = event.globalPosition().toPoint() - window.frameGeometry().topLeft()
            window.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            if free_mode:
                stop_free_movement()
            event.accept()

    def on_move(event):
        if DragState.dragging and event.buttons() == Qt.MouseButton.LeftButton:
            window.move(event.globalPosition().toPoint() - DragState.offset)
            event.accept()

    def on_release(event):
        if event.button() == Qt.MouseButton.LeftButton:
            DragState.dragging = False
            window.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            if free_mode and not locked:
                QTimer.singleShot(3000, start_free_movement)
            event.accept()

    window.mousePressEvent = on_press
    window.mouseMoveEvent = on_move
    window.mouseReleaseEvent = on_release

    # ==================== FUNCIONES AUXILIARES ====================

    def set_size(idx):
        nonlocal current_size_idx
        current_size_idx = idx
        w, h = SIZES[idx]
        geo = window.geometry()

        anim = QPropertyAnimation(window, b"geometry")
        anim.setDuration(500)
        anim.setStartValue(geo)
        anim.setEndValue(QRect(geo.x(), geo.y(), w, h))
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.start()

        def _finalize():
            view.resize(w, h)
            view.update()
            page.runJavaScript(
                "window.dispatchEvent(new Event('resize')); "
                "if(window.novaForceResize) window.novaForceResize();"
            )

        QTimer.singleShot(550, _finalize)

    def custom_size_dialog():
        w, ok1 = QInputDialog.getInt(window, "Ancho", "Ancho (px):", window.width(), 150, 1920)
        if ok1:
            h, ok2 = QInputDialog.getInt(window, "Alto", "Alto (px):", window.height(), 150, 1080)
            if ok2:
                nonlocal current_size_idx
                current_size_idx = -1
                geo = window.geometry()

                anim = QPropertyAnimation(window, b"geometry")
                anim.setDuration(500)
                anim.setStartValue(geo)
                anim.setEndValue(QRect(geo.x(), geo.y(), w, h))
                anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
                anim.start()

                def _finalize():
                    view.resize(w, h)
                    view.update()
                    page.runJavaScript(
                        "window.dispatchEvent(new Event('resize')); "
                        "if(window.novaForceResize) window.novaForceResize();"
                    )

                QTimer.singleShot(550, _finalize)

    def move_to_position(pos):
        screen = app.primaryScreen().geometry()
        margin = 15
        w, h = window.width(), window.height()

        if pos == 'center':
            target = QPoint((screen.width() - w) // 2, (screen.height() - h) // 2)
        elif pos == 'tl':
            target = QPoint(margin, margin)
        elif pos == 'tr':
            target = QPoint(screen.width() - w - margin, margin)
        elif pos == 'bl':
            target = QPoint(margin, screen.height() - h - margin)
        else:
            target = QPoint(screen.width() - w - margin, screen.height() - h - margin)

        anim = QPropertyAnimation(window, b"pos")
        anim.setDuration(700)
        anim.setStartValue(window.pos())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.InOutBack)
        anim.start()

    # ==================== PANEL DE CHAT (reemplaza el QInputDialog básico) ====================
    # Antes, "Escribir mensaje..." era un QInputDialog.getText(): una sola
    # línea, sin poder mandar nada más que texto. Este diálogo agrega texto
    # multilínea + adjuntar imágenes/archivos (documentos), sin links a
    # propósito (así lo pidió el usuario) — cada adjunto se manda como una
    # ruta de archivo real, nunca una URL.
    class NovaChatDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("💬 Chat con Nova")
            self.setMinimumSize(440, 340)
            self.archivos_adjuntos = []

            self.setStyleSheet("""
                QDialog { background-color: rgb(18, 18, 26); }
                QTextEdit {
                    background-color: rgba(255, 255, 255, 0.06);
                    border: 1px solid rgba(0, 255, 200, 0.35);
                    border-radius: 8px; padding: 10px;
                    color: #e0fff0; font-family: Segoe UI; font-size: 13px;
                }
                QListWidget {
                    background-color: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(0, 255, 200, 0.2);
                    border-radius: 6px; color: #b8ffe8; font-size: 11px;
                }
                QPushButton {
                    background-color: rgba(0, 255, 200, 0.12);
                    border: 1px solid rgba(0, 255, 200, 0.4);
                    border-radius: 6px; padding: 8px 14px;
                    color: #e0fff0; font-family: Segoe UI; font-size: 12px;
                }
                QPushButton:hover { background-color: rgba(0, 255, 200, 0.22); }
                QLabel { color: #80ffe0; font-family: Segoe UI; font-size: 11px; }
            """)

            layout = QVBoxLayout(self)

            layout.addWidget(QLabel("Escribile a Nova (podés adjuntar imágenes o archivos):"))

            self.texto_edit = QTextEdit()
            self.texto_edit.setPlaceholderText("Escribí tu mensaje acá...")
            layout.addWidget(self.texto_edit, 1)

            self.lista_adjuntos = QListWidget()
            self.lista_adjuntos.setMaximumHeight(70)
            self.lista_adjuntos.setVisible(False)
            layout.addWidget(self.lista_adjuntos)

            fila_botones = QHBoxLayout()

            btn_imagen = QPushButton("🖼️ Adjuntar imagen")
            btn_imagen.clicked.connect(self._adjuntar_imagen)
            fila_botones.addWidget(btn_imagen)

            btn_archivo = QPushButton("📎 Adjuntar archivo")
            btn_archivo.clicked.connect(self._adjuntar_archivo)
            fila_botones.addWidget(btn_archivo)

            fila_botones.addStretch()

            btn_cancelar = QPushButton("Cancelar")
            btn_cancelar.clicked.connect(self.reject)
            fila_botones.addWidget(btn_cancelar)

            btn_enviar = QPushButton("Enviar ➤")
            btn_enviar.clicked.connect(self.accept)
            fila_botones.addWidget(btn_enviar)

            layout.addLayout(fila_botones)

        def _adjuntar_imagen(self):
            rutas, _ = QFileDialog.getOpenFileNames(
                self, "Elegí una o más imágenes", "",
                "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp)"
            )
            for r in rutas:
                self._agregar_adjunto(r)

        def _adjuntar_archivo(self):
            rutas, _ = QFileDialog.getOpenFileNames(
                self, "Elegí uno o más archivos", "",
                "Documentos (*.docx *.xlsx *.pdf *.txt *.md);;Todos los archivos (*)"
            )
            for r in rutas:
                self._agregar_adjunto(r)

        def _agregar_adjunto(self, ruta):
            if ruta and ruta not in self.archivos_adjuntos:
                self.archivos_adjuntos.append(ruta)
                self.lista_adjuntos.addItem(os.path.basename(ruta))
                self.lista_adjuntos.setVisible(True)

        def obtener_mensaje(self):
            return self.texto_edit.toPlainText().strip(), list(self.archivos_adjuntos)

    # ==================== MENÚ CONTEXTUAL ====================

    def show_context_menu(pos):
        nonlocal mic_active, tts_muted

        menu = QMenu(window)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(20, 20, 30, 0.95);
                border: 1px solid rgba(0, 255, 200, 0.4);
                border-radius: 10px;
                padding: 8px;
                color: #e0fff0;
                font-family: Segoe UI;
                font-size: 12px;
            }
            QMenu::item {
                padding: 10px 28px;
                border-radius: 6px;
                margin: 2px 4px;
            }
            QMenu::item:selected {
                background-color: rgba(0, 255, 200, 0.15);
                color: #00ffc8;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(0, 255, 200, 0.15);
                margin: 6px 16px;
            }
            QMenu::section {
                color: #00ffc8;
                font-weight: bold;
                padding: 6px 20px;
            }
        """)

        # ── Estado actual de Nova (deshabilitado, solo informativo) ──
        estado_texto = "💬 En espera"
        if mic_active:
            estado_texto = "🎙️ Escuchando..."
        act_estado = QAction(estado_texto, window)
        act_estado.setEnabled(False)
        menu.addAction(act_estado)
        menu.addSeparator()

        # ── ✨ Nova ──
        menu.addSection("✨ Nova")

        act_silence = QAction("🔇 Silenciar", window)
        act_silence.triggered.connect(lambda: page.runJavaScript(
            "if(typeof setSpeaking==='function') setSpeaking(false);"
        ))
        menu.addAction(act_silence)

        act_wave = QAction("👋 Saludar", window)
        act_wave.triggered.connect(lambda: page.runJavaScript("if(typeof setState==='function') setState('waving')"))
        menu.addAction(act_wave)

        act_dance = QAction("💃 Bailar", window)
        act_dance.triggered.connect(lambda: page.runJavaScript("if(typeof setState==='function') setState('dancing')"))
        menu.addAction(act_dance)

        act_sleep = QAction("😴 Dormir", window)
        act_sleep.triggered.connect(lambda: page.runJavaScript("if(typeof setState==='function') setState('sleeping')"))
        menu.addAction(act_sleep)

        menu.addSeparator()

        # ── 💬 Chat ──
        menu.addSection("💬 Chat")

        def send_text_message():
            dialogo = NovaChatDialog(window)
            if dialogo.exec() != QDialog.DialogCode.Accepted:
                return
            texto, archivos = dialogo.obtener_mensaje()
            if not texto and not archivos:
                return

            mensaje = {'type': 'chat', 'text': texto}
            if archivos:
                mensaje['archivos'] = archivos
            try:
                resp_queue.put(mensaje, timeout=1.0)
            except Exception as e:
                print(f"[NOVA3D] Error enviando chat: {e}")

            if texto:
                safe_text = texto.replace("'", "\\'").replace('"', '\\"').replace("\n", " ")
                page.runJavaScript(
                    f"if(typeof window.novaSendMessage==='function'){{window.novaSendMessage('{safe_text}');}}"
                )
            page.runJavaScript("if(typeof setState==='function') setState('thinking');")
            QTimer.singleShot(800, lambda: page.runJavaScript(
                "if(typeof setState==='function') setState('speaking');"
            ))

        act_write = QAction("💬 Chat con Nova…", window)
        act_write.triggered.connect(send_text_message)
        menu.addAction(act_write)

        def toggle_mic():
            nonlocal mic_active
            mic_active = not mic_active
            page.runJavaScript(
                f"if(typeof window.novaToggleMic==='function'){{window.novaToggleMic({str(mic_active).lower()});}}"
            )
            if mic_active:
                page.runJavaScript("if(typeof setState==='function') setState('listening');")
            else:
                page.runJavaScript("if(typeof setState==='function') setState('idle');")

        act_mic = QAction(f"🎤 Micrófono: {'ON ✓' if mic_active else 'OFF'}", window)
        act_mic.triggered.connect(toggle_mic)
        menu.addAction(act_mic)

        def toggle_tts():
            nonlocal tts_muted
            tts_muted = not tts_muted
            page.runJavaScript(
                f"if(typeof window.novaMuteTTS==='function'){{window.novaMuteTTS({str(tts_muted).lower()});}}"
            )

        act_mute = QAction(f"🔊 Voz TTS: {'MUTE ✓' if tts_muted else 'ON'}", window)
        act_mute.triggered.connect(toggle_tts)
        menu.addAction(act_mute)

        menu.addSeparator()

        # ── 🌙 No molestar ──
        # Estas opciones no cambian nada localmente: solo avisan al proceso
        # principal (vía resp_queue) para que nova_mente_core.py aplique el
        # cambio real sobre el latido cognitivo (GestorNoMolestar).
        menu.addSection("🌙 No molestar")

        def toggle_dnd():
            nonlocal dnd_active
            dnd_active = not dnd_active
            try:
                resp_queue.put_nowait({'type': 'dnd', 'action': 'toggle'})
            except Exception as e:
                print(f"[NOVA3D] Error enviando toggle DND: {e}")

        act_dnd = QAction(f"🌙 No molestar ahora: {'ON ✓' if dnd_active else 'OFF'}", window)
        act_dnd.triggered.connect(toggle_dnd)
        menu.addAction(act_dnd)

        def agregar_app_dnd():
            nombre, ok = QInputDialog.getText(
                window, "➕ Excluir app",
                "Nombre (o parte del nombre) de la app/ventana donde\nNova NO debe interrumpir sola:",
                text=""
            )
            if ok and nombre.strip():
                try:
                    resp_queue.put_nowait({'type': 'dnd', 'action': 'add', 'app': nombre.strip()})
                except Exception as e:
                    print(f"[NOVA3D] Error enviando dnd add: {e}")

        act_dnd_add = QAction("➕ Excluir una app…", window)
        act_dnd_add.triggered.connect(agregar_app_dnd)
        menu.addAction(act_dnd_add)

        def quitar_app_dnd():
            nombre, ok = QInputDialog.getText(
                window, "➖ Quitar exclusión",
                "Nombre (o parte del nombre) de la app a quitar\nde la lista de 'no molestar':",
                text=""
            )
            if ok and nombre.strip():
                try:
                    resp_queue.put_nowait({'type': 'dnd', 'action': 'remove', 'app': nombre.strip()})
                except Exception as e:
                    print(f"[NOVA3D] Error enviando dnd remove: {e}")

        act_dnd_remove = QAction("➖ Quitar una app…", window)
        act_dnd_remove.triggered.connect(quitar_app_dnd)
        menu.addAction(act_dnd_remove)

        menu.addSeparator()

        # ── 😊 Expresiones ──
        menu.addSection("😊 Expresiones")

        expressions = [
            ("😊 Feliz", "happy", 1.0),
            ("😢 Triste", "sad", 0.9),
            ("😲 Sorprendida", "surprised", 1.0),
            ("🥰 Amor", "love", 1.0),
            ("😡 Enojada", "angry", 0.8),
            ("😴 Cansada", "tired", 0.7),
            ("😳 Tímida", "shy", 0.8),
            ("🤔 Confundida", "confused", 0.7),
        ]
        for label, expr, w in expressions:
            act = QAction(label, window)
            act.triggered.connect(lambda checked, e=expr, weight=w: page.runJavaScript(
                f"if(typeof setExpression==='function') setExpression('{e}', {weight})"
            ))
            menu.addAction(act)

        menu.addSeparator()

        # ── 🧍 Acciones ──
        menu.addSection("🧍 Acciones")

        actions = [
            ("🙆‍♀️ Estirarse", "stretching"),
            ("🙇‍♀️ Inclinarse", "bowing"),
            ("🫣 Cubrirse ojos", "shy"),
            ("💁‍♀️ Señalar", "pointing"),
            ("🧘‍♀️ Meditar", "relaxed"),
            ("🤸‍♀️ Saltar", "jumping"),
            ("✍️ Escribir", "typing"),
            ("📖 Leer", "reading"),
        ]
        for label, state in actions:
            act = QAction(label, window)
            act.triggered.connect(lambda checked, s=state: page.runJavaScript(
                f"if(typeof setState==='function') setState('{s}')"
            ))
            menu.addAction(act)

        menu.addSeparator()

        # ── 🚀 Movimiento ──
        menu.addSection("🚀 Movimiento")

        act_toggle_free = QAction("🌊 Modo libre: " + ("ON ✓" if free_mode else "OFF"), window)
        def toggle_free():
            nonlocal free_mode
            free_mode = not free_mode
            if free_mode and not locked:
                start_free_movement()
            else:
                stop_free_movement()
        act_toggle_free.triggered.connect(toggle_free)
        menu.addAction(act_toggle_free)

        act_toggle_lock = QAction("🔒 Bloquear: " + ("ON ✓" if locked else "OFF"), window)
        def toggle_lock():
            nonlocal locked
            locked = not locked
            if locked:
                stop_free_movement()
            elif free_mode:
                QTimer.singleShot(500, start_free_movement)
        act_toggle_lock.triggered.connect(toggle_lock)
        menu.addAction(act_toggle_lock)

        menu.addSeparator()

        # ── 📐 Tamaño ──
        menu.addSection("📐 Tamaño")

        size_labels = ["🔹 Pequeña", "🔸 Normal", "🔶 Grande", "🔷 Enorme"]
        for i, label in enumerate(size_labels):
            act = QAction(f"{label} {SIZES[i][0]}×{SIZES[i][1]}" + (" ✓" if current_size_idx == i else ""), window)
            act.triggered.connect(functools.partial(set_size, i))
            menu.addAction(act)

        act_custom = QAction("⚙️ Personalizado…", window)
        act_custom.triggered.connect(custom_size_dialog)
        menu.addAction(act_custom)

        menu.addSeparator()

        # ── 📍 Posiciones ──
        menu.addSection("📍 Posiciones")

        positions = [
            ("⬜ Centro", 'center'),
            ("↖️ Arriba-izq", 'tl'),
            ("↗️ Arriba-der", 'tr'),
            ("↙️ Abajo-izq", 'bl'),
            ("↘️ Abajo-der", 'br'),
        ]
        for label, position in positions:
            act = QAction(label, window)
            act.triggered.connect(functools.partial(move_to_position, position))
            menu.addAction(act)

        menu.addSeparator()

        # ── 🛑 Control de ejecución ──
        menu.addSection("🛑 Control")

        def finalizar_conversacion():
            """Cierre rápido pero seguro - mata Qt cleanly"""
            nonlocal destroyed
            destroyed = True

            def _do_exit():
                import subprocess
                import os
                
                # 1. Detener timers
                for timer in [cmd_timer, health_timer, free_timer]:
                    try:
                        if timer:
                            timer.stop()
                    except:
                        pass

                # 2. Enviar shutdown al proceso principal
                try:
                    resp_queue.put_nowait({'type': 'chat', 'text': '__SHUTDOWN__'})
                except:
                    pass

                # 3. Cerrar ventana Qt de forma limpia
                try:
                    window.close()
                except:
                    pass
                
                # 4. Dejar que Qt procese el cierre (solo 100ms)
                import time
                time.sleep(0.1)
                
                # 5. Quit Qt
                try:
                    app.quit()
                except:
                    pass
                
                # 6. Si aún no cerró, matar el proceso Qt
                time.sleep(0.1)
                subprocess.Popen("taskkill /PID %d /F" % os.getpid(), shell=True)

            _do_exit()

        act_finalizar = QAction("🛑 Finalizar conversación", window)
        act_finalizar.triggered.connect(finalizar_conversacion)
        menu.addAction(act_finalizar)

        menu.addSeparator()

        act_close = QAction("❌ Cerrar Nova", window)
        act_close.triggered.connect(lambda: process_destroy())
        menu.addAction(act_close)

        menu.exec(window.mapToGlobal(pos))

    window.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    window.customContextMenuRequested.connect(show_context_menu)

    def process_commands():
        nonlocal ready, destroyed
        if destroyed:
            cmd_timer.stop()
            return
        try:
            while not cmd_queue.empty():
                cmd = cmd_queue.get_nowait()
                if cmd['type'] == 'js':
                    page.runJavaScript(cmd['code'])
                elif cmd['type'] == 'move':
                    window.move(cmd.get('x', window.x()), cmd.get('y', window.y()))
                elif cmd['type'] == 'resize':
                    w = cmd.get('w', window.width())
                    h = cmd.get('h', window.height())
                    window.resize(w, h)
                    page.runJavaScript("window.dispatchEvent(new Event('resize'));")
                elif cmd['type'] == 'ping':
                    resp_queue.put({'status': 'pong', 'ready': ready})
                elif cmd['type'] == 'destroy':
                    process_destroy()
                elif cmd['type'] == 'shutdown':
                    process_destroy()
                elif cmd['type'] == 'shutdown_total':
                    process_destroy()
        except Exception as e:
            print(f"[NOVA3D] ⚠️ Error: {e}")

    def process_destroy():
        nonlocal destroyed
        destroyed = True
        cmd_timer.stop()
        health_timer.stop()
        if free_timer:
            free_timer.stop()
        stop_free_movement()
        if httpd:
            try:
                httpd.shutdown()
            except Exception:
                pass
        window.close()
        QTimer.singleShot(100, app.quit)

    cmd_timer = QTimer()
    cmd_timer.timeout.connect(process_commands)
    cmd_timer.start(50)
    
    
    
    def health_check():
        nonlocal ready
        if ready or destroyed:
            health_timer.stop()
            return

        def on_result(result):
            nonlocal ready
            # FIX: Evita la condición de carrera bloqueando callbacks asíncronos rezagados
            if ready or destroyed:
                return
                
            if isinstance(result, dict) and result.get('ready'):
                ready = True
                health_timer.stop() # Nos aseguramos de detener el timer inmediatamente
                print("[NOVA3D] ✅ Modelo 3D listo")
                
                if free_mode and not locked:
                    QTimer.singleShot(1500, start_free_movement)
                QTimer.singleShot(300, lambda: page.runJavaScript(
                    "window.dispatchEvent(new Event('resize')); "
                    "if(window.novaForceResize) window.novaForceResize();"
                ))

        js_code = "(() => { return (typeof window.novaPing === 'function') ? window.novaPing() : {ready: false}; })()"
        page.runJavaScript(js_code, on_result)
        
    health_timer = QTimer()
    health_timer.timeout.connect(health_check)
    health_timer.start(300)

    free_timer = QTimer()
    def check_free():
        if free_mode and not locked and not destroyed and not DragState.dragging:
            if not free_anim or free_anim.state() != QPropertyAnimation.State.Running:
                start_free_movement()
    free_timer.timeout.connect(check_free)
    free_timer.start(5000)

    print("[NOVA3D] 🚀 Nova 3D v8.8 — Arrastra el modelo, clic derecho para opciones")
    window.show()

    try:
        sys.exit(app.exec())
    except Exception as e:
        print(f"[NOVA3D] ❌ Error: {e}")
    finally:
        if httpd:
            try:
                httpd.shutdown()
            except Exception:
                pass


class Nova3D:
    VALID_STATES = {
        'idle', 'listening', 'thinking', 'speaking', 'error',
        'celebrating', 'curious', 'happy', 'sad', 'angry', 'surprised',
        'waving', 'dancing', 'pointing', 'writing', 'sleeping',
        'excited', 'confused', 'shy', 'love', 'stretching', 'yawning',
        'nodding', 'shaking', 'bowing', 'jumping', 'floating',
        'reading', 'typing', 'laughing', 'crying', 'winking'
    }

    VALID_EXPRESSIONS = {
        'happy', 'angry', 'sad', 'relaxed', 'surprised', 'neutral',
        'blink', 'blinkLeft', 'blinkRight',
        'wink', 'smile', 'frown', 'shocked', 'tired', 'determined',
        'excited', 'shy', 'love', 'confused', 'proud', 'worried'
    }

    def __init__(self, base_dir, width=320, height=440, x=100, y=100):
        self.base_dir = base_dir
        self.html_path = os.path.join(base_dir, "Nova3D", "index.html")
        self.model_path = os.path.join(base_dir, "Nova.vrm")
        self._ready = False
        self._destroyed = False
        self.win_width = width
        self.win_height = height
        self.win_x = x
        self.win_y = y
        self._cmd_queue = multiprocessing.Queue()
        self._resp_queue = multiprocessing.Queue()
        self._process = None
        self._validate_files()

    def _validate_files(self):
        errors = []
        if not os.path.exists(self.html_path):
            errors.append(f"index.html no encontrado: {self.html_path}")
        if not os.path.exists(self.model_path):
            errors.append(f"Nova.vrm no encontrado: {self.model_path}")
        js_dir = os.path.join(self.base_dir, "Nova3D", "js")
        for js in ["three.module.js", "GLTFLoader.module.js", "three-vrm.module.js"]:
            if not os.path.exists(os.path.join(js_dir, js)):
                errors.append(f"Librería JS faltante: {js}")
        if errors:
            print("[NOVA3D] 🚨 Archivos faltantes:")
            for e in errors:
                print(f"   ❌ {e}")
        else:
            print("[NOVA3D] ✅ Archivos verificados.")

    def start(self):
        if not os.path.exists(self.html_path):
            print("[NOVA3D] ❌ index.html no encontrado")
            return False
        if self._process and self._process.is_alive():
            print("[NOVA3D] ⚠️ Ya está corriendo")
            return True
        try:
            self._process = multiprocessing.Process(
                target=_qt_process,
                args=(self.win_width, self.win_height,
                      self.win_x, self.win_y, self.base_dir,
                      self._cmd_queue, self._resp_queue),
                daemon=True
            )
            self._process.start()
            print(f"[NOVA3D] 🚀 Proceso iniciado (PID: {self._process.pid})")
            threading.Thread(target=self._wait_ready, daemon=True).start()
            return True
        except Exception as e:
            print(f"[NOVA3D] ❌ Error iniciando proceso: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _wait_ready(self):
        # FIX: Aumentamos a 60 iteraciones (30 segundos) para asegurar la carga del WebGL
        for _ in range(60):
            if self._destroyed:
                return
            try:
                self._cmd_queue.put({'type': 'ping'})
                import time
                time.sleep(0.5)
                
                # FIX: Vaciar la cola de respuestas para no procesar mensajes "viejos" acumulados
                while not self._resp_queue.empty():
                    msg = self._resp_queue.get_nowait()
                    if isinstance(msg, dict) and msg.get('ready'):
                        self._ready = True
                        print("[NOVA3D] ✅ Cuerpo 3D listo")
                        return
            except Exception:
                pass
        print("[NOVA3D] ⚠️ El cuerpo 3D no respondió a tiempo")

    def _send_js(self, code):
        if self._destroyed or not self._process or not self._process.is_alive():
            return False
        try:
            self._cmd_queue.put({'type': 'js', 'code': code}, timeout=1.0)
            return True
        except Exception as e:
            print(f"[NOVA3D] Error JS: {e}")
            return False

    def _move_window(self, x=None, y=None):
        cmd = {'type': 'move'}
        if x is not None:
            cmd['x'] = x
        if y is not None:
            cmd['y'] = y
        try:
            self._cmd_queue.put(cmd, timeout=1.0)
            return True
        except Exception as e:
            print(f"[NOVA3D] Error moviendo: {e}")
            return False

    def _resize_window(self, w=None, h=None):
        cmd = {'type': 'resize'}
        if w is not None:
            cmd['w'] = w
        if h is not None:
            cmd['h'] = h
        try:
            self._cmd_queue.put(cmd, timeout=1.0)
            return True
        except Exception as e:
            print(f"[NOVA3D] Error resize: {e}")
            return False

    def state(self, s):
        if s not in self.VALID_STATES:
            s = 'idle'
        return self._send_js(f"if(typeof setState==='function') setState('{s}')")

    def expression(self, expr, weight=1.0):
        if expr not in self.VALID_EXPRESSIONS:
            return False
        w = max(0.0, min(1.0, float(weight)))
        return self._send_js(f"if(typeof setExpression==='function') setExpression('{expr}', {w})")

    def speaking(self, active):
        return self._send_js(f"if(typeof setSpeaking==='function') setSpeaking({str(bool(active)).lower()})")

    def wave(self):
        return self.state('waving')

    def dance(self):
        return self.state('dancing')

    def jump(self):
        return self.state('jumping')

    def nod(self):
        return self.state('nodding')

    def shake_head(self):
        return self.state('shaking')

    def bow(self):
        return self.state('bowing')

    def stretch(self):
        return self.state('stretching')

    def yawn(self):
        return self.state('yawning')

    def float_up(self):
        return self.state('floating')

    def read(self):
        return self.state('reading')

    def type_action(self):
        return self.state('typing')

    def laugh(self):
        return self.state('laughing')

    def cry(self):
        return self.state('crying')

    def wink(self):
        return self.expression('wink', 1.0)

    def smile(self):
        return self.expression('smile', 1.0)

    def frown(self):
        return self.expression('frown', 1.0)

    def blink(self):
        return self._send_js("if(typeof setExpression==='function'){setExpression('blink',1);setTimeout(()=>setExpression('blink',0),150)}")

    def blink_left(self):
        return self._send_js("if(typeof setExpression==='function'){setExpression('blinkLeft',1);setTimeout(()=>setExpression('blinkLeft',0),150)}")

    def blink_right(self):
        return self._send_js("if(typeof setExpression==='function'){setExpression('blinkRight',1);setTimeout(()=>setExpression('blinkRight',0),150)}")

    def move_to(self, x, y):
        return self._move_window(x, y)

    def move_random(self):
        import random
        try:
            import pyautogui
            sw, sh = pyautogui.size()
        except Exception:
            sw, sh = 1920, 1080
        x = random.randint(0, max(0, sw - self.win_width))
        y = random.randint(0, max(0, sh - self.win_height))
        return self._move_window(x, y)

    def resize(self, width, height):
        self.win_width = width
        self.win_height = height
        return self._resize_window(width, height)

    def reset_position(self):
        return self._move_window(self.win_x, self.win_y)

    def esta_vivo(self) -> bool:
        """Chequeo liviano (sin mandar nada por la cola) de si el subproceso
        del cuerpo 3D sigue corriendo. Usado por NovaApp para detectar un
        crash nativo de Qt6WebEngineCore (ej. violación de acceso 0xc0000005
        por presión de memoria) y reiniciarlo solo, en vez de dejar a Nova
        sin cuerpo para siempre y sin ningún aviso."""
        return self._process is not None and self._process.is_alive()

    def is_ready(self):
        return self._ready and not self._destroyed and self._process is not None and self._process.is_alive()

    def poll_chat(self):
        # NOTA: se mantiene por compatibilidad, pero tiene un problema conocido:
        # si el mensaje en cola no es de tipo 'chat' (p.ej. un 'dnd'), lo saca
        # de la cola igual y lo descarta en silencio. Para código nuevo usar
        # poll_events(), que no pierde mensajes de otros tipos.
        if self._destroyed or not self._process or not self._process.is_alive():
            return None
        try:
            if not self._resp_queue.empty():
                msg = self._resp_queue.get_nowait()
                if msg.get('type') == 'chat':
                    return msg.get('text')
        except Exception:
            pass
        return None

    def poll_events(self):
        """Devuelve una lista con TODOS los mensajes pendientes de la ventana 3D
        (chat, no-molestar, etc.), sin descartar ninguno. Preferir esta función
        sobre poll_chat() para no perder eventos de tipos distintos a 'chat'."""
        eventos = []
        if self._destroyed or not self._process or not self._process.is_alive():
            return eventos
        try:
            while not self._resp_queue.empty():
                eventos.append(self._resp_queue.get_nowait())
        except Exception:
            pass
        return eventos

    def close(self):
        print("[NOVA3D] 👋 Cerrando cuerpo 3D...")
        self._destroyed = True
        self._ready = False
        try:
            self._cmd_queue.put({'type': 'destroy'}, timeout=2.0)
            import time
            time.sleep(0.5)
        except Exception as e:
            print(f"[NOVA3D] Error destroy: {e}")

        if self._process and self._process.is_alive():
            try:
                self._process.terminate()
                self._process.join(timeout=3)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join(timeout=1)
            except Exception as e:
                print(f"[NOVA3D] Error cerrando: {e}")
        self._process = None
        print("[NOVA3D] ✅ Cuerpo 3D cerrado.")


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    ctrl = Nova3D(base, width=320, height=440, x=100, y=100)
    ctrl.start()
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        ctrl.close()