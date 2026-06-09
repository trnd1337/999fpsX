# 999fpsx.py
"""
999fpsx - GUI with vendor CLI integration (AMD) and extended settings.
Now with full auto-save + auto-load of last session, and forced Windows
fallback backend for applying profiles (even on AMD/Intel).

Features:
- Telemetry (freq, temp, load)
- Windows power plan import/export and rename
- Profiles (JSON) with optional .pow export
- Auto-import .pow on startup
- Vendor CLI integration (AMD Ryzen Master CLI detection + custom command template)
- Extra settings: PL1/PL2 fields, PBO attempt toggle
- Dark theme and icon
- Full auto-save on exit and auto-load on startup (last_session.json)
"""

import sys
import os
import subprocess
import json
import time
import shutil
from datetime import datetime
from pathlib import Path

from PyQt5 import QtWidgets, QtCore, QtGui
import psutil
import pyqtgraph as pg

# Optional WMI for additional temperature sources
try:
    import wmi
    _wmi = wmi.WMI()
except Exception:
    _wmi = None

APP_TITLE = "999fpsX - CPU Profile Manager"
LOGFILE = Path("999fpsx.log")
LOCAL_PROFILES_DIR = Path("profiles")
USER_APP_DIR = Path(os.getenv("APPDATA") or Path.home() / ".config") / "999fpsx"
USER_PROFILES_DIR = USER_APP_DIR / "profiles"
USER_PROFILES_DIR.mkdir(parents=True, exist_ok=True)

LAST_SESSION_FILE = USER_APP_DIR / "last_session.json"

ICON_FILENAME = Path("icon.png")
AUTO_ELEVATE = False

# Default auto-import plan settings
DEFAULT_AUTO_IMPORT_GUID = "8acb232b-aa83-4027-a633-5f1c6bb71308"
DEFAULT_POW_FILENAME = "999fps.pow"


# -------------------------
# Resource helpers & logging
# -------------------------
def log(msg: str) -> None:
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")
    except Exception:
        pass


def is_admin() -> bool:
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def relaunch_as_admin() -> None:
    import ctypes
    params = " ".join([f'"{p}"' for p in sys.argv])
    executable = sys.executable
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
    except Exception as e:
        print("Elevation failed:", e)


def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, shell=False)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def read_cpu_temp():
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for key in temps:
                entries = temps[key]
                if entries:
                    return entries[0].current
    except Exception:
        pass
    if _wmi:
        try:
            for sensor in _wmi.MSAcpi_ThermalZoneTemperature():
                temp_c = sensor.CurrentTemperature / 10.0 - 273.15
                return temp_c
        except Exception:
            pass
    return None


def detect_vendor() -> str:
    try:
        if sys.platform.startswith("win"):
            code, out, err = run_cmd(["wmic", "cpu", "get", "Manufacturer,Name", "/format:list"])
            info = (out or err).lower()
            if "amd" in info or "ryzen" in info:
                return "AMD"
            if "intel" in info:
                return "Intel"
    except Exception:
        pass
    return "Unknown"


# -------------------------
# PyInstaller-aware resource helpers
# -------------------------
def get_resource_path(rel_path: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return (base / rel_path).resolve()


def ensure_default_profiles_copied() -> None:
    try:
        bundled = get_resource_path("profiles")
        user = USER_PROFILES_DIR
        user.mkdir(parents=True, exist_ok=True)
        if bundled.exists() and bundled.is_dir():
            for p in bundled.glob("*"):
                dest = user / p.name
                if not dest.exists():
                    try:
                        shutil.copy2(p, dest)
                        log(f"Copied bundled profile {p.name} to user profiles")
                    except Exception as e:
                        log(f"Failed to copy bundled profile {p.name}: {e}")
    except Exception as e:
        log(f"ensure_default_profiles_copied error: {e}")


ensure_default_profiles_copied()


# -------------------------
# Backends
# -------------------------
class BackendBase:
    def available(self):
        return False

    def read_telemetry(self):
        return {}

    def apply_profile(self, profile):
        raise NotImplementedError

    def revert(self):
        raise NotImplementedError


class WindowsFallbackBackend(BackendBase):
    HIGH_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"

    def __init__(self):
        self.saved = {}

    def available(self):
        return True

    def read_telemetry(self):
        freq = psutil.cpu_freq()
        return {
            "freq": freq.current if freq else None,
            "load": psutil.cpu_percent(interval=None),
            "temp": read_cpu_temp()
        }

    def apply_profile(self, profile):
        self.saved["active"] = self.get_active()
        run_cmd(["powercfg", "/setactive", self.HIGH_GUID])
        run_cmd([
            "powercfg",
            "/setacvalueindex",
            "SCHEME_CURRENT",
            "SUB_PROCESSOR",
            "PROCTHROTTLEMAX",
            str(profile.get("max_processor_state_ac", 100)),
        ])
        if "max_processor_state_dc" in profile:
            run_cmd([
                "powercfg",
                "/setdcvalueindex",
                "SCHEME_CURRENT",
                "SUB_PROCESSOR",
                "PROCTHROTTLEMAX",
                str(profile.get("max_processor_state_dc", 100)),
            ])
        run_cmd(["powercfg", "/S", "SCHEME_CURRENT"])
        if profile.get("disable_core_parking"):
            run_cmd([
                "powercfg",
                "/setacvalueindex",
                "SCHEME_CURRENT",
                "SUB_PROCESSOR",
                "CPUPARKINGMAXCORES",
                "100",
            ])
            run_cmd([
                "powercfg",
                "/setacvalueindex",
                "SCHEME_CURRENT",
                "SUB_PROCESSOR",
                "CPUPARKINGMINCORES",
                "0",
            ])
            run_cmd(["powercfg", "/S", "SCHEME_CURRENT"])
        log("Windows fallback applied profile")
        return True, "Applied"

    def revert(self):
        if "active" in self.saved and self.saved["active"]:
            run_cmd(["powercfg", "/setactive", self.saved["active"]])
            log("Windows fallback restored power plan")
        return True, "Restored"

    def get_active(self):
        code, out, err = run_cmd(["powercfg", "/getactivescheme"])
        if code == 0 and out:
            parts = out.split(":")
            if len(parts) > 1:
                return parts[1].strip().split()[0]
        return None


class AmdBackend(BackendBase):
    def available(self):
        return True

    def read_telemetry(self):
        freq = psutil.cpu_freq()
        return {
            "freq": freq.current if freq else None,
            "load": psutil.cpu_percent(interval=None),
            "temp": read_cpu_temp(),
        }

    def apply_profile(self, profile):
        return False, "Use Vendor Control to apply AMD vendor profiles"

    def revert(self):
        return True, "AMD revert stub"


class IntelBackend(BackendBase):
    def available(self):
        return True

    def read_telemetry(self):
        freq = psutil.cpu_freq()
        return {
            "freq": freq.current if freq else None,
            "load": psutil.cpu_percent(interval=None),
            "temp": read_cpu_temp(),
        }

    def apply_profile(self, profile):
        return False, "Intel vendor integration not implemented"

    def revert(self):
        return True, "Intel revert stub"


# -------------------------
# Telemetry and profile manager
# -------------------------
class TelemetryThread(QtCore.QThread):
    telemetry = QtCore.pyqtSignal(dict)

    def __init__(self, backend, interval=0.8):
        super().__init__()
        self.backend = backend
        self.interval = interval
        self._running = True

    def run(self):
        while self._running:
            try:
                data = self.backend.read_telemetry()
                self.telemetry.emit(data)
            except Exception as e:
                log(f"Telemetry error {e}")
            time.sleep(self.interval)

    def stop(self):
        self._running = False


class ProfileManager:
    def __init__(self):
        self.user_dir = USER_PROFILES_DIR

    def save(self, name, data):
        path = self.user_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        log(f"Saved profile {name}")

    def load(self, name):
        path = self.user_dir / f"{name}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def list(self):
        return [p.stem for p in self.user_dir.glob("*.json")]


# -------------------------
# Vendor CLI integration (AMD)
# -------------------------
def find_amd_cli_candidates():
    candidates = [
        r"C:\Program Files\AMD\RyzenMaster\AMDRyzenMaster.exe",
        r"C:\Program Files\AMDRyzenMaster\AMDRMCLI.exe",
        r"C:\Program Files (x86)\AMDRyzenMaster\AMDRMCLI.exe",
        r"C:\Program Files (x86)\AMD\RyzenMaster\AMDRyzenMaster.exe",
    ]
    return [Path(p) for p in candidates if Path(p).exists()]


def run_vendor_command(cli_path: str, args: list):
    try:
        cmd = [str(cli_path)] + args
        code, out, err = run_cmd(cmd)
        return code, out, err
    except Exception as e:
        return -1, "", str(e)


# -------------------------
# Main Window
# -------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        if AUTO_ELEVATE and not is_admin():
            relaunch_as_admin()
            QtWidgets.QMessageBox.information(
                None,
                "Elevation",
                "Relaunching with administrator privileges. Please re-run the app if needed.",
            )
            sys.exit(0)

        self.thermal_limit = 92.0
        self.boost_active = False
        self.history = {"freq": [], "temp": [], "load": []}
        self.max_history = 300

        self.settings = {
            "thermal_cutoff": float(self.thermal_limit),
            "disable_core_parking": False,
            "max_processor_state_ac": 100,
            "max_processor_state_dc": 100,
            "telemetry_interval": 0.8,
            "affinity_mode": "all",
            "custom_affinity_mask": 0,
            "profile_name": "custom",
            "auto_import_plan": True,
            "auto_import_path": str((USER_PROFILES_DIR / DEFAULT_POW_FILENAME).resolve()),
            "auto_import_activate": True,
            "auto_import_guid": DEFAULT_AUTO_IMPORT_GUID,
            "vendor_cli_path": "",
            "vendor_profile_name": "",
            "vendor_command_template": "{cli} -a ApplyProfile \"{profile}\"",
            "attempt_pbo": False,
            "pl1_watts": 0,
            "pl2_watts": 0,
            "rollback_seconds": 20,
        }

        self._load_last_session()

        self.setWindowTitle(APP_TITLE)
        self.setGeometry(200, 200, 1100, 700)

        icon_path = get_resource_path("icon.png")
        if icon_path.exists():
            pix = QtGui.QPixmap(str(icon_path))
            if not pix.isNull():
                self.setWindowIcon(QtGui.QIcon(pix))
        else:
            img = QtGui.QImage(64, 64, QtGui.QImage.Format_ARGB32)
            img.fill(QtGui.QColor("#2b2b2b"))
            painter = QtGui.QPainter(img)
            painter.setPen(QtGui.QColor("#ffffff"))
            font = QtGui.QFont("Sans", 20, QtGui.QFont.Bold)
            painter.setFont(font)
            painter.drawText(img.rect(), QtCore.Qt.AlignCenter, "999")
            painter.end()
            self.setWindowIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(img)))

        self.vendor = detect_vendor()
        log(f"Detected vendor: {self.vendor}")

        # Force Windows fallback backend for all vendors
        self.backend = WindowsFallbackBackend()
        log("Forcing WindowsFallbackBackend for profile application")

        self.pmgr = ProfileManager()
        self.telemetry_thread = TelemetryThread(
            self.backend, interval=self.settings["telemetry_interval"]
        )
        self.telemetry_thread.telemetry.connect(self.on_telemetry)

        self.rollback_timer = QtCore.QTimer()
        self.rollback_timer.setSingleShot(True)
        self.rollback_timer.timeout.connect(self._on_rollback_timeout)
        self.rollback_seconds = int(self.settings.get("rollback_seconds", 20))

        self.init_ui()
        self.apply_dark_theme()
        self.telemetry_thread.start()

        QtCore.QTimer.singleShot(500, self._maybe_auto_import_on_startup)

        self.append_log("App started (auto-load applied if available)")

    # -------------------------
    # Auto-save / auto-load
    # -------------------------
    def _load_last_session(self):
        try:
            if LAST_SESSION_FILE.exists():
                with open(LAST_SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saved_settings = data.get("settings", {})
                for k, v in saved_settings.items():
                    self.settings[k] = v
                log("Loaded last_session.json")
        except Exception as e:
            log(f"Failed to load last_session.json: {e}")

    def _save_last_session(self):
        try:
            USER_APP_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "settings": self.settings,
                "timestamp": datetime.now().isoformat(),
            }
            with open(LAST_SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            log("Saved last_session.json")
        except Exception as e:
            log(f"Failed to save last_session.json: {e}")

    # -------------------------
    # UI
    # -------------------------
    def apply_dark_theme(self):
        dark = """
        QWidget { background: #121212; color: #e6e6e6; }
        QGroupBox { border: 1px solid #2a2a2a; margin-top: 6px; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; color: #ffffff; }
        QPushButton { background: #1f1f1f; border: 1px solid #333; padding: 6px; }
        QPushButton:hover { background: #2a2a2a; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit { background: #1b1b1b; border: 1px solid #333; color: #e6e6e6; }
        QCheckBox { spacing: 6px; }
        QLabel { color: #e6e6e6; }
        QToolTip { background: #2b2b2b; color: #ffffff; border: 1px solid #444; }
        """
        self.setStyleSheet(dark)

    def init_ui(self):
        central = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout()

        top = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel(f"Status Idle  Vendor: {self.vendor}")
        top.addWidget(self.status)
        top.addStretch()
        self.admin_label = QtWidgets.QLabel("Admin: " + str(is_admin()))
        top.addWidget(self.admin_label)
        main_layout.addLayout(top)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # Left side: graphs + logs
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout()

        graph_widget = pg.GraphicsLayoutWidget()
        self.freq_plot = graph_widget.addPlot(title="CPU Frequency MHz")
        self.freq_curve = self.freq_plot.plot(pen=pg.mkPen("#00ccff", width=2))
        graph_widget.nextRow()
        self.temp_plot = graph_widget.addPlot(title="CPU Temperature °C")
        self.temp_curve = self.temp_plot.plot(pen=pg.mkPen("#ff6600", width=2))
        graph_widget.nextRow()
        self.load_plot = graph_widget.addPlot(title="CPU Load %")
        self.load_curve = self.load_plot.plot(pen=pg.mkPen("#66ff66", width=2))
        left_layout.addWidget(graph_widget, 3)

        self.log_view = QtWidgets.QTextEdit()
        self.log_view.setReadOnly(True)
        left_layout.addWidget(self.log_view, 1)

        left_widget.setLayout(left_layout)
        splitter.addWidget(left_widget)

        # Right side: settings, vendor, profiles, power plans
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout()

        # Settings group
        settings_group = QtWidgets.QGroupBox("Settings")
        s_layout = QtWidgets.QFormLayout()

        self.thermal_spin = QtWidgets.QSpinBox()
        self.thermal_spin.setRange(60, 110)
        self.thermal_spin.setValue(int(self.settings["thermal_cutoff"]))
        self.thermal_spin.valueChanged.connect(
            lambda v: self.on_setting_change("thermal_cutoff", float(v))
        )
        s_layout.addRow("Thermal cutoff (°C)", self.thermal_spin)

        self.max_ac_spin = QtWidgets.QSpinBox()
        self.max_ac_spin.setRange(1, 100)
        self.max_ac_spin.setValue(int(self.settings["max_processor_state_ac"]))
        self.max_ac_spin.setSuffix(" %")
        self.max_ac_spin.valueChanged.connect(
            lambda v: self.on_setting_change("max_processor_state_ac", int(v))
        )
        s_layout.addRow("Max processor state (AC)", self.max_ac_spin)

        self.max_dc_spin = QtWidgets.QSpinBox()
        self.max_dc_spin.setRange(1, 100)
        self.max_dc_spin.setValue(int(self.settings["max_processor_state_dc"]))
        self.max_dc_spin.setSuffix(" %")
        self.max_dc_spin.valueChanged.connect(
            lambda v: self.on_setting_change("max_processor_state_dc", int(v))
        )
        s_layout.addRow("Max processor state (DC)", self.max_dc_spin)

        self.park_chk = QtWidgets.QCheckBox("Disable core parking")
        self.park_chk.setChecked(self.settings["disable_core_parking"])
        self.park_chk.stateChanged.connect(
            lambda s: self.on_setting_change("disable_core_parking", bool(s))
        )
        s_layout.addRow(self.park_chk)

        self.telemetry_spin = QtWidgets.QDoubleSpinBox()
        self.telemetry_spin.setRange(0.2, 5.0)
        self.telemetry_spin.setSingleStep(0.1)
        self.telemetry_spin.setValue(float(self.settings["telemetry_interval"]))
        self.telemetry_spin.valueChanged.connect(
            lambda v: self.on_setting_change("telemetry_interval", float(v))
        )
        s_layout.addRow("Telemetry interval (s)", self.telemetry_spin)

        self.affinity_combo = QtWidgets.QComboBox()
        self.affinity_combo.addItems(["all", "even", "odd", "custom"])
        self.affinity_combo.setCurrentText(self.settings["affinity_mode"])
        self.affinity_combo.currentTextChanged.connect(
            lambda t: self.on_setting_change("affinity_mode", t)
        )
        s_layout.addRow("Affinity mode", self.affinity_combo)

        self.affinity_mask_edit = QtWidgets.QLineEdit(
            hex(int(self.settings.get("custom_affinity_mask", 0)))
        )
        self.affinity_mask_edit.setToolTip(
            "Hex mask of logical cores, e.g., 0xF for first 4 cores"
        )
        self.affinity_mask_edit.editingFinished.connect(
            self._on_affinity_mask_changed
        )
        s_layout.addRow("Custom affinity mask", self.affinity_mask_edit)

        self.pl1_spin = QtWidgets.QSpinBox()
        self.pl1_spin.setRange(0, 1000)
        self.pl1_spin.setValue(int(self.settings.get("pl1_watts", 0)))
        self.pl1_spin.setSuffix(" W")
        self.pl1_spin.valueChanged.connect(
            lambda v: self.on_setting_change("pl1_watts", int(v))
        )
        s_layout.addRow("PL1 (Watts)", self.pl1_spin)

        self.pl2_spin = QtWidgets.QSpinBox()
        self.pl2_spin.setRange(0, 2000)
        self.pl2_spin.setValue(int(self.settings.get("pl2_watts", 0)))
        self.pl2_spin.setSuffix(" W")
        self.pl2_spin.valueChanged.connect(
            lambda v: self.on_setting_change("pl2_watts", int(v))
        )
        s_layout.addRow("PL2 (Watts)", self.pl2_spin)

        self.pbo_chk = QtWidgets.QCheckBox(
            "Attempt PBO enable via vendor CLI (if available)"
        )
        self.pbo_chk.setChecked(self.settings.get("attempt_pbo", False))
        self.pbo_chk.stateChanged.connect(
            lambda s: self.on_setting_change("attempt_pbo", bool(s))
        )
        s_layout.addRow(self.pbo_chk)

        self.rollback_spin = QtWidgets.QSpinBox()
        self.rollback_spin.setRange(5, 300)
        self.rollback_spin.setValue(int(self.settings.get("rollback_seconds", 20)))
        self.rollback_spin.setSuffix(" s")
        self.rollback_spin.valueChanged.connect(self._on_rollback_changed)
        s_layout.addRow("Rollback window", self.rollback_spin)

        settings_group.setLayout(s_layout)
        right_layout.addWidget(settings_group)

        # Vendor Control group
        vendor_group = QtWidgets.QGroupBox("Vendor Control (AMD)")
        v_layout = QtWidgets.QFormLayout()

        self.vendor_cli_edit = QtWidgets.QLineEdit(
            self.settings.get("vendor_cli_path", "")
        )
        self.vendor_cli_edit.setPlaceholderText(
            "Path to vendor CLI (AMDRyzenMaster/AMDRMCLI)"
        )
        v_layout.addRow("Vendor CLI", self.vendor_cli_edit)

        vendor_browse = QtWidgets.QPushButton("Browse")

        def _browse_vendor():
            fn, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select vendor CLI executable",
                str(Path.cwd()),
                "Executables (*.exe);;All files (*)",
            )
            if fn:
                self.vendor_cli_edit.setText(fn)
                self.on_setting_change("vendor_cli_path", fn)

        vendor_browse.clicked.connect(_browse_vendor)
        v_layout.addRow("", vendor_browse)

        self.vendor_profile_edit = QtWidgets.QLineEdit(
            self.settings.get("vendor_profile_name", "")
        )
        self.vendor_profile_edit.setPlaceholderText(
            "Vendor profile name (if applicable)"
        )
        v_layout.addRow("Vendor profile", self.vendor_profile_edit)

        self.vendor_template_edit = QtWidgets.QLineEdit(
            self.settings.get("vendor_command_template", "")
        )
        self.vendor_template_edit.setToolTip(
            "Template: {cli} and {profile} will be replaced. Example: {cli} -a ApplyProfile \"{profile}\""
        )
        v_layout.addRow("Command template", self.vendor_template_edit)

        vendor_btns = QtWidgets.QHBoxLayout()
        self.detect_vendor_btn = QtWidgets.QPushButton("Auto-detect CLI")
        self.detect_vendor_btn.clicked.connect(self._detect_vendor_cli)
        vendor_btns.addWidget(self.detect_vendor_btn)

        self.apply_vendor_btn = QtWidgets.QPushButton("Apply Vendor Profile")
        self.apply_vendor_btn.clicked.connect(self._apply_vendor_profile)
        vendor_btns.addWidget(self.apply_vendor_btn)

        self.revert_vendor_btn = QtWidgets.QPushButton("Revert Vendor Profile")
        self.revert_vendor_btn.clicked.connect(self._revert_vendor_profile)
        vendor_btns.addWidget(self.revert_vendor_btn)

        v_layout.addRow(vendor_btns)
        vendor_group.setLayout(v_layout)
        right_layout.addWidget(vendor_group)

        # Profiles group
        profile_group = QtWidgets.QGroupBox("Profiles")
        p_layout = QtWidgets.QHBoxLayout()

        self.profile_name = QtWidgets.QLineEdit(
            self.settings.get("profile_name", "custom")
        )
        p_layout.addWidget(self.profile_name)

        self.include_powerplan_chk = QtWidgets.QCheckBox(
            "Include power plan (.pow) with profile"
        )
        self.include_powerplan_chk.setChecked(False)
        p_layout.addWidget(self.include_powerplan_chk)

        self.save_profile_btn = QtWidgets.QPushButton("Save")
        self.save_profile_btn.clicked.connect(self.save_profile)
        p_layout.addWidget(self.save_profile_btn)

        self.load_combo = QtWidgets.QComboBox()
        self.refresh_profiles()
        p_layout.addWidget(self.load_combo)

        self.load_profile_btn = QtWidgets.QPushButton("Load")
        self.load_profile_btn.clicked.connect(self.load_profile)
        p_layout.addWidget(self.load_profile_btn)

        profile_group.setLayout(p_layout)
        right_layout.addWidget(profile_group)

        # Power plans group
        plan_group = QtWidgets.QGroupBox("Power Plans")
        pg_layout = QtWidgets.QHBoxLayout()

        self.plan_combo = QtWidgets.QComboBox()
        self.plan_name_edit = QtWidgets.QLineEdit()
        self.plan_name_edit.setPlaceholderText("Enter new plan name")

        self.rename_plan_btn = QtWidgets.QPushButton("Rename Plan")
        self.rename_plan_btn.clicked.connect(self.rename_selected_plan)

        refresh_btn = QtWidgets.QPushButton("Refresh Plans")
        refresh_btn.clicked.connect(self.refresh_power_plans_ui)

        pg_layout.addWidget(self.plan_combo, 2)
        pg_layout.addWidget(self.plan_name_edit, 2)
        pg_layout.addWidget(self.rename_plan_btn)
        pg_layout.addWidget(refresh_btn)

        plan_group.setLayout(pg_layout)
        right_layout.addWidget(plan_group)
        self.refresh_power_plans_ui()

        # Auto-import group
        auto_group = QtWidgets.QGroupBox("Auto Import Plan")
        ag_layout = QtWidgets.QHBoxLayout()

        self.auto_import_chk = QtWidgets.QCheckBox("Auto import on startup")
        self.auto_import_chk.setChecked(self.settings.get("auto_import_plan", False))
        self.auto_import_chk.stateChanged.connect(
            lambda s: self.on_setting_change("auto_import_plan", bool(s))
        )
        ag_layout.addWidget(self.auto_import_chk)

        self.auto_activate_chk = QtWidgets.QCheckBox("Activate after import")
        self.auto_activate_chk.setChecked(
            self.settings.get("auto_import_activate", False)
        )
        self.auto_activate_chk.stateChanged.connect(
            lambda s: self.on_setting_change("auto_import_activate", bool(s))
        )
        ag_layout.addWidget(self.auto_activate_chk)

        self.auto_path_edit = QtWidgets.QLineEdit(
            self.settings.get("auto_import_path", "")
        )
        self.auto_path_edit.setPlaceholderText("Path to .pow file")
        self.auto_path_edit.editingFinished.connect(
            lambda: self.on_setting_change(
                "auto_import_path", self.auto_path_edit.text().strip()
            )
        )
        ag_layout.addWidget(self.auto_path_edit)

        pick_btn = QtWidgets.QPushButton("Browse")

        def _pick_pow():
            fn, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select power plan file",
                str(USER_PROFILES_DIR),
                "Power plan (*.pow);;All files (*)",
            )
            if fn:
                self.auto_path_edit.setText(fn)
                self.on_setting_change("auto_import_path", fn)

        pick_btn.clicked.connect(_pick_pow)
        ag_layout.addWidget(pick_btn)

        import_btn = QtWidgets.QPushButton("Import Now")
        import_btn.clicked.connect(self._manual_import_now)
        ag_layout.addWidget(import_btn)

        auto_group.setLayout(ag_layout)
        right_layout.addWidget(auto_group)

        # Actions
        actions_layout = QtWidgets.QHBoxLayout()
        self.preview_btn = QtWidgets.QPushButton("Preview Changes")
        self.preview_btn.clicked.connect(self.preview_changes)
        actions_layout.addWidget(self.preview_btn)

        self.apply_btn = QtWidgets.QPushButton("Apply Settings")
        self.apply_btn.clicked.connect(self.apply_settings_now)
        actions_layout.addWidget(self.apply_btn)

        self.revert_btn = QtWidgets.QPushButton("Revert")
        self.revert_btn.clicked.connect(self.revert)
        actions_layout.addWidget(self.revert_btn)

        right_layout.addLayout(actions_layout)

        self.helper_label = QtWidgets.QLabel(
            "Preview shows the commands that will run. Apply/Import/Vendor require Admin."
        )
        right_layout.addWidget(self.helper_label)
        right_layout.addStretch()

        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)

        main_layout.addWidget(splitter)
        central.setLayout(main_layout)
        self.setCentralWidget(central)

    # -------------------------
    # UI helpers and settings
    # -------------------------
    def append_log(self, text: str):
        self.log_view.append(f"{datetime.now().strftime('%H:%M:%S')} {text}")
        log(text)

    def refresh_profiles(self):
        self.load_combo.clear()
        for p in self.pmgr.list():
            self.load_combo.addItem(p)

    def _on_affinity_mask_changed(self):
        txt = self.affinity_mask_edit.text().strip()
        try:
            if txt.lower().startswith("0x"):
                mask = int(txt, 16)
            else:
                mask = int(txt)
            self.on_setting_change("custom_affinity_mask", int(mask))
        except Exception:
            self.append_log("Invalid affinity mask format")

    def _on_rollback_changed(self, v: int):
        self.rollback_seconds = int(v)
        self.on_setting_change("rollback_seconds", self.rollback_seconds)
        self.append_log(f"Rollback window set to {self.rollback_seconds} s")

    def on_setting_change(self, key, value):
        self.settings[key] = value
        self.append_log(f"Setting changed: {key} = {value}")
        if key == "telemetry_interval":
            try:
                self.telemetry_thread.stop()
                self.telemetry_thread.wait(1000)
            except Exception:
                pass
            self.telemetry_thread = TelemetryThread(self.backend, interval=value)
            self.telemetry_thread.telemetry.connect(self.on_telemetry)
            self.telemetry_thread.start()

    def on_telemetry(self, data: dict):
        freq = data.get("freq") or 0
        temp = data.get("temp") or 0
        load = data.get("load") or 0

        self.history["freq"].append(freq)
        self.history["temp"].append(temp)
        self.history["load"].append(load)

        for k in self.history:
            if len(self.history[k]) > self.max_history:
                self.history[k].pop(0)

        self.freq_curve.setData(self.history["freq"])
        self.temp_curve.setData(self.history["temp"])
        self.load_curve.setData(self.history["load"])

        if (
            self.boost_active
            and temp
            and temp >= self.settings.get("thermal_cutoff", self.thermal_limit)
        ):
            self.append_log(f"Thermal limit reached {temp:.1f} °C. Reverting.")
            self.revert()

    def _gather_profile_from_settings(self):
        p = {
            "thermal_cutoff": float(
                self.settings.get("thermal_cutoff", self.thermal_limit)
            ),
            "disable_core_parking": bool(
                self.settings.get("disable_core_parking", False)
            ),
            "max_processor_state_ac": int(
                self.settings.get("max_processor_state_ac", 100)
            ),
            "max_processor_state_dc": int(
                self.settings.get("max_processor_state_dc", 100)
            ),
            "telemetry_interval": float(
                self.settings.get("telemetry_interval", 0.8)
            ),
            "affinity_mode": self.settings.get("affinity_mode", "all"),
            "custom_affinity_mask": int(
                self.settings.get("custom_affinity_mask", 0)
            ),
            "vendor_profile_name": self.vendor_profile_edit.text().strip(),
        }
        return p

    def _build_preview_text(self, profile: dict) -> str:
        lines = []
        lines.append("The following actions will be performed:")
        lines.append(
            f"- Set active power plan to High Performance (GUID {WindowsFallbackBackend.HIGH_GUID})"
        )
        lines.append(
            f"- Set max processor state (AC) to {profile.get('max_processor_state_ac', 100)}%"
        )
        lines.append(
            f"- Set max processor state (DC) to {profile.get('max_processor_state_dc', 100)}%"
        )
        if profile.get("disable_core_parking"):
            lines.append("- Disable core parking (AC)")
        else:
            lines.append("- Leave core parking unchanged")
        affinity = profile.get("affinity_mode", "all")
        lines.append(f"- Affinity mode: {affinity}")
        if affinity == "custom":
            lines.append(
                f"  - Custom affinity mask: 0x{profile.get('custom_affinity_mask', 0):X}"
            )
        lines.append(
            f"- Thermal cutoff: {profile.get('thermal_cutoff')} °C (auto-revert if exceeded)"
        )
        lines.append(
            f"- Rollback window: {self.rollback_seconds} seconds (auto revert unless confirmed)"
        )
        if self.settings.get("pl1_watts"):
            lines.append(
                f"- PL1 target: {self.settings.get('pl1_watts')} W (applied via vendor CLI if supported)"
            )
        if self.settings.get("pl2_watts"):
            lines.append(
                f"- PL2 target: {self.settings.get('pl2_watts')} W (applied via vendor CLI if supported)"
            )
        if self.settings.get("attempt_pbo"):
            lines.append(
                "- Attempt to enable PBO via vendor CLI (if available)"
            )
        return "\n".join(lines)

    def preview_changes(self):
        profile = self._gather_profile_from_settings()
        text = self._build_preview_text(profile)
        dlg = QtWidgets.QMessageBox(self)
        dlg.setWindowTitle("Preview Changes")
        dlg.setText(text)
        dlg.setStandardButtons(QtWidgets.QMessageBox.Ok)
        dlg.exec_()

    def apply_settings_now(self):
        if not is_admin():
            self.append_log("Administrator required to apply settings")
            QtWidgets.QMessageBox.warning(
                self,
                "Admin required",
                "Run as Administrator to apply system settings",
            )
            return
        if self.boost_active:
            self.append_log("Settings already applied")
            return

        profile = self._gather_profile_from_settings()
        ok, msg = self.backend.apply_profile(profile)
        self.append_log(f"Apply profile: {ok} {msg}")

        if ok:
            self._apply_affinity(profile)
            self.boost_active = True
            self.status.setText("Status Boost Active")
            self.rollback_timer.start(self.rollback_seconds * 1000)
            self.append_log(
                f"Rollback timer started for {self.rollback_seconds} seconds"
            )
            if self.settings.get("vendor_cli_path"):
                if (
                    self.settings.get("attempt_pbo")
                    or self.settings.get("pl1_watts")
                    or self.settings.get("pl2_watts")
                ):
                    self.append_log(
                        "Attempting vendor CLI adjustments (PBO/PL)"
                    )
                    self._apply_vendor_power_limits()
        else:
            self.append_log("Failed to apply profile")

    def _apply_affinity(self, profile: dict):
        mode = profile.get("affinity_mode", "all")
        try:
            pid = os.getpid()
            p = psutil.Process(pid)
            cpu_count = psutil.cpu_count()

            if mode == "all":
                p.cpu_affinity(list(range(cpu_count)))
                self.append_log("Affinity set to all cores for current process")
            elif mode == "even":
                cores = [i for i in range(cpu_count) if i % 2 == 0]
                p.cpu_affinity(cores)
                self.append_log(f"Affinity set to even cores: {cores}")
            elif mode == "odd":
                cores = [i for i in range(cpu_count) if i % 2 == 1]
                p.cpu_affinity(cores)
                self.append_log(f"Affinity set to odd cores: {cores}")
            elif mode == "custom":
                mask = int(profile.get("custom_affinity_mask", 0))
                cores = []
                for i in range(cpu_count):
                    if mask & (1 << i):
                        cores.append(i)
                if cores:
                    p.cpu_affinity(cores)
                    self.append_log(f"Affinity set to custom cores: {cores}")
                else:
                    self.append_log(
                        "Custom affinity mask produced no cores; no change"
                    )
        except Exception as e:
            self.append_log(f"Affinity apply error: {e}")

    def _on_rollback_timeout(self):
        self.append_log("Rollback timer expired; reverting settings")
        self.revert()

    def revert(self):
        try:
            ok, msg = self.backend.revert()
            self.append_log(f"Revert: {ok} {msg}")
        except Exception as e:
            self.append_log(f"Revert error: {e}")

        if self.rollback_timer.isActive():
            self.rollback_timer.stop()
        self.boost_active = False
        self.status.setText("Status Idle")

    # -------------------------
    # Power plan helpers
    # -------------------------
    def _get_power_plans(self):
        code, out, err = run_cmd(["powercfg", "/L"])
        plans = []
        text = out or err or ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.lower().startswith("power scheme guid:"):
                try:
                    parts = line.split(":", 1)[1].strip()
                    guid = parts.split()[0]
                    name_part = (
                        line[line.find("(") + 1 : line.rfind(")")]
                        if "(" in line and ")" in line
                        else ""
                    )
                    active = line.endswith("*")
                    plans.append((guid, name_part, active))
                except Exception:
                    continue
        return plans

    def refresh_power_plans_ui(self):
        try:
            plans = self._get_power_plans()
            self.plan_combo.clear()
            for guid, name, active in plans:
                label = f"{name}  [{guid}]"
                if active:
                    label += " *active*"
                self.plan_combo.addItem(label, guid)
            self.append_log("Power plans refreshed")
        except Exception as e:
            self.append_log(f"Error refreshing power plans: {e}")

    def rename_selected_plan(self):
        if not is_admin():
            QtWidgets.QMessageBox.warning(
                self,
                "Admin required",
                "Run the app as Administrator to rename power plans",
            )
            self.append_log("Rename aborted: admin required")
            return

        idx = self.plan_combo.currentIndex()
        if idx < 0:
            self.append_log("No power plan selected")
            return

        guid = self.plan_combo.itemData(idx)
        new_name = self.plan_name_edit.text().strip()
        if not new_name:
            self.append_log("New name required")
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm rename",
            f"Rename plan {guid} to:\n\n\"{new_name}\"?\n\nThis requires Administrator privileges.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            self.append_log("Rename cancelled by user")
            return

        code, out, err = run_cmd(["powercfg", "-changename", guid, new_name])
        if code == 0:
            self.append_log(f"Renamed plan {guid} -> {new_name}")
            QtWidgets.QMessageBox.information(
                self, "Success", "Power plan renamed successfully"
            )
            self.refresh_power_plans_ui()
        else:
            self.append_log(f"Rename failed: {err or out}")
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Rename failed: {err or out}"
            )

    # -------------------------
    # Import/export power plans
    # -------------------------
    def export_current_plan(self, out_path: str):
        if not is_admin():
            return False, "Administrator required to export plan"

        code, out, err = run_cmd(["powercfg", "/getactivescheme"])
        if code != 0:
            return False, err or out or "Failed to get active scheme"

        guid = None
        try:
            parts = (out or err).split(":")
            if len(parts) > 1:
                guid = parts[1].strip().split()[0]
        except Exception:
            guid = None

        if not guid:
            return False, "Could not parse active plan GUID"

        code, out, err = run_cmd(["powercfg", "-export", out_path, guid])
        if code == 0:
            return True, f"Exported to {out_path}"
        return False, err or out or "Export failed"

    def import_powerplan_file(
        self, pow_path: str, set_active: bool = False, guid: str | None = None
    ):
        if not is_admin():
            return False, "Administrator required to import plan"
        if not Path(pow_path).exists():
            return False, "File not found"

        code, out, err = run_cmd(["powercfg", "-import", str(pow_path)])
        if code != 0:
            return False, err or out or "Import failed"

        if set_active and guid:
            code2, out2, err2 = run_cmd(["powercfg", "/setactive", guid])
            if code2 != 0:
                return False, err2 or out2 or "Import succeeded but failed to set active"
            self.refresh_power_plans_ui()
            return True, f"Imported and activated {guid}"

        self.refresh_power_plans_ui()
        return True, "Imported (no GUID activation requested)"

    def _manual_import_now(self):
        path = self.auto_path_edit.text().strip()
        if not path:
            self.append_log("No .pow file selected")
            return
        if not is_admin():
            QtWidgets.QMessageBox.warning(
                self, "Admin required", "Run as Administrator to import power plans"
            )
            self.append_log("Manual import aborted: admin required")
            return

        ok, msg = self.import_powerplan_file(
            path,
            set_active=self.auto_activate_chk.isChecked(),
            guid=self.settings.get("auto_import_guid"),
        )
        self.append_log(f"Manual import: {ok} {msg}")
        if ok:
            QtWidgets.QMessageBox.information(self, "Import", msg)
        else:
            QtWidgets.QMessageBox.critical(self, "Import failed", msg)

    def _maybe_auto_import_on_startup(self):
        try:
            auto = self.settings.get("auto_import_plan", False)
            path = self.settings.get("auto_import_path", "")
            activate = self.settings.get("auto_import_activate", False)
            guid = self.settings.get("auto_import_guid", None)

            if auto and path:
                p = Path(path)
                if not p.exists():
                    candidate = USER_PROFILES_DIR / Path(path).name
                    if candidate.exists():
                        path = str(candidate)
                self.append_log(
                    f"Attempting auto-import of {path} (activate={activate})"
                )
                ok, msg = self.import_powerplan_file(
                    path, set_active=activate, guid=guid
                )
                self.append_log(f"Auto-import: {ok} {msg}")
                if not ok and "Administrator required" in msg:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Admin required",
                        "Auto-import requires Administrator privileges. Relaunch the app as Administrator to import and activate the plan.",
                    )
        except Exception as e:
            self.append_log(f"Auto-import error: {e}")

    # -------------------------
    # Vendor CLI UI actions
    # -------------------------
    def _detect_vendor_cli(self):
        candidates = find_amd_cli_candidates()
        if candidates:
            chosen = str(candidates[0])
            self.vendor_cli_edit.setText(chosen)
            self.on_setting_change("vendor_cli_path", chosen)
            self.append_log(f"Detected AMD CLI at {chosen}")
            QtWidgets.QMessageBox.information(
                self, "Detected", f"Detected AMD CLI: {chosen}"
            )
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Not found",
                "No AMD CLI found in common locations. Please browse to the vendor CLI executable.",
            )
            self.append_log("AMD CLI not found in common locations")

    def _apply_vendor_profile(self):
        cli = self.vendor_cli_edit.text().strip()
        profile = self.vendor_profile_edit.text().strip()
        template = (
            self.vendor_template_edit.text().strip()
            or self.settings.get("vendor_command_template", "")
        )

        if not cli:
            self.append_log("Vendor CLI path not set")
            QtWidgets.QMessageBox.warning(
                self, "Vendor CLI", "Set vendor CLI path first"
            )
            return
        if not Path(cli).exists():
            self.append_log("Vendor CLI path invalid")
            QtWidgets.QMessageBox.warning(
                self, "Vendor CLI", "Vendor CLI executable not found"
            )
            return

        try:
            if template and "{cli}" in template:
                cmd_str = (
                    template.replace("{cli}", cli)
                    .replace("{profile}", profile)
                )
                parts = cmd_str.split()
                code, out, err = run_cmd(parts)
            else:
                args = (
                    [cli, "-a", "ApplyProfile", profile]
                    if profile
                    else [cli, "-a", "ApplyProfile"]
                )
                code, out, err = run_cmd(args)

            if code == 0:
                self.append_log(
                    f"Vendor profile applied: {profile} (cli={cli})"
                )
                QtWidgets.QMessageBox.information(
                    self, "Vendor", f"Vendor profile applied: {profile}"
                )
            else:
                self.append_log(f"Vendor apply failed: {err or out}")
                QtWidgets.QMessageBox.critical(
                    self, "Vendor error", f"Apply failed: {err or out}"
                )
        except Exception as e:
            self.append_log(f"Vendor apply exception: {e}")
            QtWidgets.QMessageBox.critical(
                self, "Vendor error", f"Exception: {e}"
            )

    def _revert_vendor_profile(self):
        cli = self.vendor_cli_edit.text().strip()
        if not cli or not Path(cli).exists():
            self.append_log("Vendor CLI path invalid for revert")
            QtWidgets.QMessageBox.warning(
                self, "Vendor CLI", "Vendor CLI executable not found"
            )
            return
        try:
            args = [cli, "-a", "ResetProfile"]
            code, out, err = run_cmd(args)
            if code == 0:
                self.append_log("Vendor profile reverted (ResetProfile)")
                QtWidgets.QMessageBox.information(
                    self, "Vendor", "Vendor profile reverted"
                )
                return
            code2, out2, err2 = run_cmd([cli])
            self.append_log(
                f"Vendor revert fallback: {code2} {out2 or err2}"
            )
            QtWidgets.QMessageBox.information(
                self, "Vendor", "Vendor revert attempted; check logs"
            )
        except Exception as e:
            self.append_log(f"Vendor revert exception: {e}")
            QtWidgets.QMessageBox.critical(
                self, "Vendor error", f"Exception: {e}"
            )

    def _apply_vendor_power_limits(self):
        cli = self.vendor_cli_edit.text().strip()
        if not cli or not Path(cli).exists():
            self.append_log(
                "Vendor CLI not set; skipping vendor power limit application"
            )
            return

        pl1 = int(self.settings.get("pl1_watts", 0) or 0)
        pl2 = int(self.settings.get("pl2_watts", 0) or 0)
        template = (
            self.vendor_template_edit.text().strip()
            or self.settings.get("vendor_command_template", "")
        )

        if "{pl1}" in template or "{pl2}" in template:
            cmd_str = (
                template.replace("{cli}", cli)
                .replace("{pl1}", str(pl1))
                .replace("{pl2}", str(pl2))
                .replace("{profile}", self.vendor_profile_edit.text().strip())
            )
            parts = cmd_str.split()
            code, out, err = run_cmd(parts)
            self.append_log(
                f"Vendor PL command executed: {code} {out or err}"
            )
        else:
            self.append_log(
                "No vendor command template for PL1/PL2 provided; skipping PL application"
            )

    # -------------------------
    # Profiles (JSON) and optional powerplan export
    # -------------------------
    def save_profile(self):
        name = self.profile_name.text().strip()
        if not name:
            self.append_log("Profile name required")
            return

        self.on_setting_change("profile_name", name)
        data = {
            "settings": self.settings.copy(),
            "timestamp": datetime.now().isoformat(),
        }
        self.pmgr.save(name, data)

        if self.include_powerplan_chk.isChecked():
            pow_out = USER_PROFILES_DIR / f"{name}.pow"
            ok, msg = self.export_current_plan(str(pow_out))
            if ok:
                self.append_log(
                    f"Exported power plan with profile: {pow_out.name}"
                )
            else:
                self.append_log(f"Failed to export power plan: {msg}")

        self.refresh_profiles()
        self.append_log(f"Profile {name} saved")

    def load_profile(self):
        name = self.load_combo.currentText()
        if not name:
            self.append_log("No profile selected")
            return

        data = self.pmgr.load(name)
        if not data:
            self.append_log("Failed to load profile")
            return

        loaded = data.get("settings", {})
        self.settings.update(loaded)

        self.thermal_spin.setValue(
            int(self.settings.get("thermal_cutoff", self.thermal_limit))
        )
        self.park_chk.setChecked(
            self.settings.get("disable_core_parking", False)
        )
        self.max_ac_spin.setValue(
            int(self.settings.get("max_processor_state_ac", 100))
        )
        self.max_dc_spin.setValue(
            int(self.settings.get("max_processor_state_dc", 100))
        )
        self.telemetry_spin.setValue(
            float(self.settings.get("telemetry_interval", 0.8))
        )
        self.affinity_combo.setCurrentText(
            self.settings.get("affinity_mode", "all")
        )
        self.affinity_mask_edit.setText(
            hex(int(self.settings.get("custom_affinity_mask", 0)))
        )
        self.profile_name.setText(name)
        self.vendor_cli_edit.setText(
            self.settings.get("vendor_cli_path", "")
        )
        self.vendor_profile_edit.setText(
            self.settings.get("vendor_profile_name", "")
        )
        self.vendor_template_edit.setText(
            self.settings.get("vendor_command_template", "")
        )
        self.pl1_spin.setValue(int(self.settings.get("pl1_watts", 0)))
        self.pl2_spin.setValue(int(self.settings.get("pl2_watts", 0)))
        self.pbo_chk.setChecked(
            bool(self.settings.get("attempt_pbo", False))
        )
        self.rollback_spin.setValue(
            int(self.settings.get("rollback_seconds", 20))
        )

        self.append_log(f"Profile {name} loaded")

    def closeEvent(self, event):
        try:
            self.settings["thermal_cutoff"] = float(self.thermal_spin.value())
            self.settings["disable_core_parking"] = bool(
                self.park_chk.isChecked()
            )
            self.settings["max_processor_state_ac"] = int(
                self.max_ac_spin.value()
            )
            self.settings["max_processor_state_dc"] = int(
                self.max_dc_spin.value()
            )
            self.settings["telemetry_interval"] = float(
                self.telemetry_spin.value()
            )
            self.settings["affinity_mode"] = self.affinity_combo.currentText()

            try:
                txt = self.affinity_mask_edit.text().strip()
                if txt.lower().startswith("0x"):
                    mask = int(txt, 16)
                else:
                    mask = int(txt)
                self.settings["custom_affinity_mask"] = mask
            except Exception:
                pass

            self.settings["pl1_watts"] = int(self.pl1_spin.value())
            self.settings["pl2_watts"] = int(self.pl2_spin.value())
            self.settings["attempt_pbo"] = bool(self.pbo_chk.isChecked())
            self.settings["rollback_seconds"] = int(
                self.rollback_spin.value()
            )
            self.settings["vendor_cli_path"] = (
                self.vendor_cli_edit.text().strip()
            )
            self.settings["vendor_profile_name"] = (
                self.vendor_profile_edit.text().strip()
            )
            self.settings["vendor_command_template"] = (
                self.vendor_template_edit.text().strip()
            )
            self.settings["auto_import_plan"] = bool(
                self.auto_import_chk.isChecked()
            )
            self.settings["auto_import_activate"] = bool(
                self.auto_activate_chk.isChecked()
            )
            self.settings["auto_import_path"] = (
                self.auto_path_edit.text().strip()
            )
            self.settings["profile_name"] = (
                self.profile_name.text().strip() or "custom"
            )

            self._save_last_session()
        except Exception as e:
            self.append_log(f"Error during auto-save on exit: {e}")

        try:
            self.telemetry_thread.stop()
            self.telemetry_thread.wait(1000)
        except Exception:
            pass

        if self.boost_active:
            self.revert()

        event.accept()


# -------------------------
# Main
# -------------------------
def main():
    QtWidgets.QApplication.setAttribute(
        QtCore.Qt.AA_EnableHighDpiScaling, True
    )
    QtWidgets.QApplication.setAttribute(
        QtCore.Qt.AA_UseHighDpiPixmaps, True
    )

    app = QtWidgets.QApplication(sys.argv)

    ensure_default_profiles_copied()

    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
