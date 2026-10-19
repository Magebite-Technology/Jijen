# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI workflow for object-level semantic and geometric surface contours.

The command asks for one object. It automatically detects regions, then lets
users choose a geometric grouping or a semantic role such as top, bottom, side,
or sole candidate. Individual face picking is never required.
"""

from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import time

import FreeCAD as App

import SurfaceContours as contours
import SurfaceRegions as regions
import SurfaceSemantics as semantics

WORKER_TIMEOUT_MS = 120000
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


def _tr(text):
    return App.Qt.translate("SurfaceContours", text)


def run_detection_worker(request_path, response_path):
    """Isolated, read-only geometry job. No GUI or document is accessed.

    Only the parent owns temporary files. A killed worker cannot modify the
    live document. Protocol success is explicit: process exit alone is not.
    """
    response = {"schema": 1, "ok": False}
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        if request.get("schema") != 1:
            raise ValueError("Unsupported contour worker protocol")
        import Part
        shape = Part.Shape()
        shape.read(request["shape"])
        last = [0.0]

        def progress(stage, completed, total):
            now = time.monotonic()
            if now - last[0] >= 0.1:
                print("JIJEN_PROGRESS:" + json.dumps([stage, completed, total]), flush=True)
                last[0] = now

        with contours.contour_operation(progress):
            detection = regions.detect_surface_regions(shape, policy=request["policy"])
            semantic = None
            selected = detection
            if request["mode"] == "semantic":
                semantic = semantics.classify_surface_regions(shape, detection,
                    reference_direction=request["direction"])
                selected = semantics.select_semantic_regions(semantic, request["role"])
            results = contours.extract_region_contours(shape, selected)
            encoded = []
            for result in results:
                encoded.append({"region_id": result.region_id,
                    "component_id": result.component_id,
                    "face_indices": result.face_indices, "status": result.status,
                    "diagnostics": result.diagnostics,
                    "wires": [wire.exportBrepToString() for wire in result.wires]})
            semantic_regions = []
            if semantic:
                for item in semantic.regions:
                    data = {name: getattr(item, name) for name in item.__dataclass_fields__}
                    normal = data["average_normal"]
                    data["average_normal"] = None if normal is None else [normal.x, normal.y, normal.z]
                    semantic_regions.append(data)
            response = {"schema": 1, "ok": True, "detection": {
                "settings": asdict(detection.settings),
                "regions": [asdict(item) for item in detection.regions],
                "adjacency": detection.adjacency}, "semantic": semantic_regions,
                "semantic_diagnostics": list(semantic.diagnostics) if semantic else [],
                "results": encoded}
    except Exception as error:
        response["error"] = type(error).__name__ + ": " + str(error)
    payload = json.dumps(response)
    if len(payload.encode("utf-8")) > MAX_RESPONSE_BYTES:
        payload = json.dumps({"schema": 1, "ok": False, "error": "Contour result exceeds the safe response limit"})
    destination = Path(response_path)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(destination)


def decode_worker_response(payload, direction):
    """Validate transport envelopes before constructing any native shapes."""
    if len(payload.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise ValueError("Contour result exceeds the safe response limit")
    data = json.loads(payload)
    if data.get("schema") != 1 or data.get("ok") is not True:
        raise RuntimeError(data.get("error", "Incomplete contour worker response"))
    import Part
    detection = data["detection"]
    detection = regions.RegionDetection(regions.DetectionSettings(**detection["settings"]),
        tuple(regions.SurfaceRegion(**{**item, "face_indices": tuple(item["face_indices"]),
              "diagnostics": tuple(item["diagnostics"])}) for item in detection["regions"]),
        tuple(tuple(pair) for pair in detection["adjacency"]))
    semantic = None
    if data["semantic"]:
        items = []
        for item in data["semantic"]:
            normal = item["average_normal"]
            item["average_normal"] = None if normal is None else App.Vector(*normal)
            for name in ("face_indices", "roles", "surface_types", "diagnostics"):
                item[name] = tuple(item[name])
            items.append(semantics.SemanticRegion(**item))
        semantic = semantics.SemanticDetection(semantics.SemanticSettings(direction),
            tuple(items), tuple(data["semantic_diagnostics"]))
    results = []
    for item in data["results"]:
        wires = []
        for brep in item["wires"]:
            shape = Part.Shape()
            shape.importBrepFromString(brep)
            if shape.ShapeType != "Wire" or not shape.isValid():
                raise ValueError("Worker returned an invalid contour wire")
            wires.append(shape.Wires[0])
        results.append(contours.RegionContour(item["region_id"], item["component_id"],
            tuple(item["face_indices"]), item["status"], tuple(wires), tuple(item["diagnostics"])))
    return detection, semantic, tuple(results)


def selected_document_object(selection):
    """Return the only selected document object, or None."""
    if selection is None or len(selection) != 1:
        return None
    candidate = selection[0]
    return candidate if isinstance(candidate, App.DocumentObject) else None


def selection_message(selection):
    """Return a user-facing validation message for an object selection."""
    if not selection:
        return "Select exactly one Part object, then refresh the contour list."
    if len(selection) != 1:
        return "Select exactly one Part object; face-by-face selection is not required."
    if selected_document_object(selection) is None:
        return "The selection is not a document object with a resolvable shape."
    return ""


if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

    _USER_ROLE = QtCore.Qt.UserRole


    class SurfaceContourTaskPanel:
        """Task panel for object-level region and semantic-role contours."""

        def __init__(self):
            self.source = None
            self.detection = None
            self.semantic_detection = None
            self.results = ()
            self._building = False
            self._busy = False
            self._closing = False
            self._cancelled = False
            self._progress_dialog = None
            self._worker = None
            self._source_revision = None

            self.form = QtWidgets.QWidget()
            self.form.setWindowTitle(_tr("Surface contours"))
            layout = QtWidgets.QVBoxLayout(self.form)

            intro = QtWidgets.QLabel(_tr(
                "Select one object in the model tree. Regions are detected automatically. "
                "Choose a semantic role and reference direction for top, bottom, side, "
                "or sole-like contours; no individual face picking is needed."
            ))
            intro.setWordWrap(True)
            layout.addWidget(intro)

            source_row = QtWidgets.QHBoxLayout()
            source_row.addWidget(QtWidgets.QLabel(_tr("Object:")))
            self.source_edit = QtWidgets.QLineEdit()
            self.source_edit.setReadOnly(True)
            source_row.addWidget(self.source_edit, 1)
            self.refresh_button = QtWidgets.QPushButton(_tr("Refresh selection"))
            self.refresh_button.clicked.connect(self.refresh)
            source_row.addWidget(self.refresh_button)
            layout.addLayout(source_row)

            mode_row = QtWidgets.QHBoxLayout()
            mode_row.addWidget(QtWidgets.QLabel(_tr("Selection mode:")))
            self.mode_combo = QtWidgets.QComboBox()
            self.mode_combo.addItem(_tr("Geometric regions"), "geometric")
            self.mode_combo.addItem(_tr("Semantic surface role"), "semantic")
            self.mode_combo.currentIndexChanged.connect(self._mode_changed)
            mode_row.addWidget(self.mode_combo, 1)
            layout.addLayout(mode_row)

            policy_row = QtWidgets.QHBoxLayout()
            policy_row.addWidget(QtWidgets.QLabel(_tr("Grouping:")))
            self.policy_combo = QtWidgets.QComboBox()
            self.policy_combo.addItem(_tr("Coplanar connected regions"), "coplanar")
            self.policy_combo.addItem(_tr("Every individual face"), "individual")
            self.policy_combo.currentIndexChanged.connect(self.refresh)
            policy_row.addWidget(self.policy_combo, 1)
            layout.addLayout(policy_row)

            direction_row = QtWidgets.QHBoxLayout()
            direction_row.addWidget(QtWidgets.QLabel(_tr("Reference direction:")))
            self.direction_combo = QtWidgets.QComboBox()
            self.direction_combo.addItem("+Z / top", App.Vector(0, 0, 1))
            self.direction_combo.addItem("-Z / bottom", App.Vector(0, 0, -1))
            self.direction_combo.addItem("+X / right", App.Vector(1, 0, 0))
            self.direction_combo.addItem("-X / left", App.Vector(-1, 0, 0))
            self.direction_combo.addItem("+Y / front", App.Vector(0, 1, 0))
            self.direction_combo.addItem("-Y / back", App.Vector(0, -1, 0))
            self.direction_combo.currentIndexChanged.connect(self.refresh)
            direction_row.addWidget(self.direction_combo, 1)
            layout.addLayout(direction_row)

            role_row = QtWidgets.QHBoxLayout()
            role_row.addWidget(QtWidgets.QLabel(_tr("Surface role:")))
            self.role_combo = QtWidgets.QComboBox()
            self.role_combo.addItem("All semantic regions", "all")
            self.role_combo.addItem("Top-facing", "top")
            self.role_combo.addItem("Bottom-facing", "bottom")
            self.role_combo.addItem("Side", "side")
            self.role_combo.addItem("Sole candidate", "sole_candidate")
            self.role_combo.addItem("Unknown / ambiguous", "unknown")
            self.role_combo.currentIndexChanged.connect(self.refresh)
            role_row.addWidget(self.role_combo, 1)
            layout.addLayout(role_row)

            self.region_list = QtWidgets.QListWidget()
            self.region_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            self.region_list.currentRowChanged.connect(self._region_changed)
            layout.addWidget(self.region_list, 1)

            self.detail_label = QtWidgets.QLabel(_tr("No region selected."))
            self.detail_label.setWordWrap(True)
            layout.addWidget(self.detail_label)

            actions = QtWidgets.QHBoxLayout()
            self.create_button = QtWidgets.QPushButton(_tr("Create parametric preview"))
            self.create_button.clicked.connect(self.create_selected)
            self.create_all_button = QtWidgets.QPushButton(_tr("Create all parametric previews"))
            self.create_all_button.clicked.connect(self.create_all)
            actions.addWidget(self.create_button)
            actions.addWidget(self.create_all_button)
            layout.addLayout(actions)

            self.status_label = QtWidgets.QLabel()
            self.status_label.setWordWrap(True)
            layout.addWidget(self.status_label)
            self._update_semantic_controls()
            QtCore.QTimer.singleShot(0, self.refresh)

        def getStandardButtons(self):
            return int(QtGui.QDialogButtonBox.Close)

        def _policy(self):
            return self.policy_combo.currentData()

        def _mode(self):
            return self.mode_combo.currentData()

        def _role(self):
            return self.role_combo.currentData()

        def _direction(self):
            direction = self.direction_combo.currentData()
            if hasattr(direction, "toPyObject"):
                direction = direction.toPyObject()
            return direction

        def _update_semantic_controls(self):
            semantic_mode = self._mode() == "semantic"
            self.direction_combo.setEnabled(semantic_mode)
            self.role_combo.setEnabled(semantic_mode)

        def _mode_changed(self):
            self._update_semantic_controls()
            self.refresh()

        def _set_status(self, text, error=False):
            # Use the platform palette; error meaning must not depend on colour.
            self.status_label.setText(_tr("Error: %s") % text if error else text)
            self.status_label.setAccessibleName(_tr("Contour status"))

        def _cancel(self):
            self._cancelled = True
            if self._worker is not None:
                self._worker.kill()
            if self._progress_dialog is not None:
                self._progress_dialog.setLabelText(_tr("Cancelling…"))

        def _detect_isolated(self, snapshot):
            """Keep the event loop responsive even during a native kernel call."""
            candidates = [Path(App.getHomePath()) / "bin" / name
                          for name in ("FreeCADCmd.exe", "FreeCADCmd", "freecadcmd")]
            executable = next((path for path in candidates if path.is_file()), None)
            if executable is None:
                raise RuntimeError(_tr("Cannot find the bundled FreeCAD command-line runtime"))
            with tempfile.TemporaryDirectory(prefix="jijen-contours-") as directory:
                folder = Path(directory)
                shape_path, request_path, response_path = (folder / "source.brep",
                    folder / "request.json", folder / "response.json")
                snapshot.exportBrep(str(shape_path))
                direction = self._direction()
                request_path.write_text(json.dumps({"schema": 1, "shape": str(shape_path),
                    "policy": self._policy(), "mode": self._mode(), "role": self._role(),
                    "direction": [direction.x, direction.y, direction.z]}), encoding="utf-8")
                code = ("import sys; sys.path.insert(0, %r); import SurfaceContourGui as worker; "
                        "worker.run_detection_worker(%r, %r)" %
                        (str(Path(__file__).resolve().parent), str(request_path), str(response_path)))
                process = QtCore.QProcess(self.form)
                self._worker = process
                loop = QtCore.QEventLoop()
                timer = QtCore.QTimer(self.form)
                timer.setSingleShot(True)
                timed_out = [False]
                output_buffer = [""]

                def timeout():
                    timed_out[0] = True
                    process.kill()

                def read_progress():
                    # Drain output continuously; never let a pipe stall the worker.
                    output_buffer[0] += bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
                    process.readAllStandardError()
                    lines = output_buffer[0].split("\n")
                    output_buffer[0] = lines.pop()[-65536:]
                    for line in lines:
                        if line.startswith("JIJEN_PROGRESS:"):
                            try:
                                stage, completed, total = json.loads(line.split(":", 1)[1])
                            except (ValueError, TypeError):
                                continue
                            dialog = self._progress_dialog
                            if dialog is not None:
                                dialog.setLabelText(_tr(stage))
                                if isinstance(total, int) and total > 0:
                                    dialog.setRange(0, total)
                                    dialog.setValue(completed or 0)
                                else:
                                    dialog.setRange(0, 0)

                process.readyReadStandardOutput.connect(read_progress)
                process.readyReadStandardError.connect(read_progress)
                process.finished.connect(loop.quit)
                process.errorOccurred.connect(loop.quit)
                timer.timeout.connect(timeout)
                timer.start(WORKER_TIMEOUT_MS)
                try:
                    process.start(str(executable), ["--safe-mode", "--console", code])
                    loop.exec_()
                    if self._cancelled or self._closing:
                        raise contours.ContourCancelled()
                    if timed_out[0]:
                        raise RuntimeError(_tr("Contour detection exceeded the two-minute limit"))
                    if process.exitStatus() != QtCore.QProcess.NormalExit or process.exitCode() != 0 or not response_path.is_file():
                        raise RuntimeError(_tr("Contour worker failed; no document changes were made"))
                    return decode_worker_response(response_path.read_text(encoding="utf-8"), direction)
                finally:
                    timer.stop()
                    if process.state() != QtCore.QProcess.NotRunning:
                        process.kill()
                        process.waitForFinished(1000)
                    self._worker = None
                    process.deleteLater()
                    timer.deleteLater()

        def _progress(self, stage, completed=None, total=None):
            if self._cancelled or self._closing:
                raise contours.ContourCancelled()
            now = time.monotonic()
            if now - self._last_progress < 0.05:
                return
            self._last_progress = now
            dialog = self._progress_dialog
            if dialog is not None:
                dialog.setLabelText(_tr(stage))
                if total is not None and total > 0:
                    dialog.setRange(0, total)
                    dialog.setValue(completed or 0)
                QtWidgets.QApplication.processEvents()
                if dialog.wasCanceled() or self._cancelled or self._closing:
                    raise contours.ContourCancelled()

        @contextmanager
        def _operation(self, title):
            self._busy = True
            self._cancelled = False
            self._last_progress = 0.0
            controls = (self.refresh_button, self.mode_combo, self.policy_combo,
                        self.direction_combo, self.role_combo, self.region_list,
                        self.create_button, self.create_all_button)
            for control in controls:
                control.setEnabled(False)
            dialog = QtWidgets.QProgressDialog(_tr(title), _tr("Cancel"), 0, 0, Gui.getMainWindow())
            dialog.setWindowTitle(_tr("Surface contours"))
            dialog.setWindowModality(QtCore.Qt.ApplicationModal)
            dialog.setMinimumDuration(0)
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.canceled.connect(self._cancel)
            self._progress_dialog = dialog
            dialog.show()
            try:
                with contours.contour_operation(self._progress):
                    yield
            finally:
                self._progress_dialog = None
                dialog.close()
                dialog.deleteLater()
                self._busy = False
                for control in controls:
                    control.setEnabled(True)
                self._update_semantic_controls()
                self.create_button.setEnabled(bool(self.results))
                self.create_all_button.setEnabled(bool(self.results))
                if self._closing:
                    QtCore.QTimer.singleShot(0, Gui.Control.closeDialog)

        def refresh(self):
            if self._busy or self._closing or not hasattr(self, "region_list"):
                return
            try:
                with self._operation("Reading geometry…"):
                    self._refresh()
            except contours.ContourCancelled:
                self.results = ()
                self.detection = None
                self.semantic_detection = None
                self.region_list.clear()
                self.create_button.setEnabled(False)
                self.create_all_button.setEnabled(False)
                self.detail_label.setText("No region selected.")
                self._set_status("Cancelled. Refresh selection to try again.")
            except Exception as error:
                self.results = ()
                self.region_list.clear()
                self.create_button.setEnabled(False)
                self.create_all_button.setEnabled(False)
                self._set_status("Contour detection failed: %s" % error, error=True)

        def _refresh(self):
            if not hasattr(self, "region_list"):
                return
            self._building = True
            try:
                selection = Gui.Selection.getSelection()
                self.source = selected_document_object(selection)
                self.detection = None
                self.semantic_detection = None
                self.results = ()
                self.region_list.clear()
                self.detail_label.setText("No region selected.")
                message = selection_message(selection)
                if message:
                    self.source_edit.clear()
                    self._set_status(message, error=True)
                    self.create_button.setEnabled(False)
                    self.create_all_button.setEnabled(False)
                    return

                self.source_edit.setText(self.source.Label)
                try:
                    snapshot = contours.resolve_shape(self.source).copy()
                    self._source_revision = contours.shape_revision(snapshot)
                    self.detection, self.semantic_detection, self.results = self._detect_isolated(snapshot)
                    if self._mode() == "semantic" and self.semantic_detection is not None:
                        semantic_by_id = {
                            item.region_id: item for item in self.semantic_detection.regions
                        }
                    else:
                        semantic_by_id = {}
                except contours.ContourCancelled:
                    raise
                except Exception as error:
                    self._set_status("Contour detection failed: %s" % error, error=True)
                    self.create_button.setEnabled(False)
                    self.create_all_button.setEnabled(False)
                    return

                for ordinal, result in enumerate(self.results):
                    contours.checkpoint("Loading region list", ordinal, len(self.results))
                    if self._mode() == "semantic":
                        item_data = semantic_by_id[result.region_id]
                        label = (
                            "%s · %s · confidence %.2f · %d face(s) · %s"
                            % (
                                result.region_id,
                                item_data.primary_role,
                                item_data.confidence,
                                len(result.face_indices),
                                result.status,
                            )
                        )
                    else:
                        label = "%s · %s · %d face(s) · %s" % (
                            result.region_id,
                            result.component_id,
                            len(result.face_indices),
                            result.status,
                        )
                    item = QtWidgets.QListWidgetItem(label)
                    item.setData(_USER_ROLE, result.region_id)
                    self.region_list.addItem(item)
                if self.results:
                    self.region_list.setCurrentRow(0)
                self.create_button.setEnabled(bool(self.results))
                self.create_all_button.setEnabled(bool(self.results))
                if self._mode() == "semantic":
                    self._set_status(
                        "%d semantic region(s) matched role '%s' along %s. "
                        "Classification is heuristic and confidence-scored."
                        % (
                            len(self.results),
                            self._role(),
                            self.direction_combo.currentText(),
                        )
                    )
                else:
                    self._set_status(
                        "%d region(s) detected. Created previews update when the source "
                        "is recomputed." % len(self.results)
                    )
            finally:
                self._building = False

        def _region_changed(self, row):
            if row < 0 or row >= len(self.results):
                self.detail_label.setText("No region selected.")
                return
            result = self.results[row]
            diagnostic = "; ".join(result.diagnostics) if result.diagnostics else "none"
            if self._mode() == "semantic" and self.semantic_detection:
                semantic = next(
                    item for item in self.semantic_detection.regions
                    if item.region_id == result.region_id
                )
                self.detail_label.setText(
                    "%s: role=%s, confidence=%.2f, orientation=%.3f, elevation=%.3f. "
                    "%d boundary wire(s), %d face(s). Diagnostics: %s"
                    % (
                        result.status,
                        semantic.primary_role,
                        semantic.confidence,
                        semantic.orientation_score,
                        semantic.position_score,
                        len(result.wires),
                        len(result.face_indices),
                        diagnostic,
                    )
                )
            else:
                self.detail_label.setText(
                    "%s: %d boundary wire(s), %d face(s). Diagnostics: %s"
                    % (result.status, len(result.wires), len(result.face_indices), diagnostic)
                )

        def _create(self, selected):
            if self._busy or self._closing:
                return ()
            try:
                with self._operation("Creating preview…"):
                    if contours.shape_revision(self.source) != self._source_revision:
                        raise RuntimeError(_tr("Source changed. Refresh the contour list before creating a preview."))
                    with contours.prepared_analysis(self.source, self.detection,
                            self.semantic_detection, self.results, self._source_revision):
                        return self._create_result(selected)
            except contours.ContourCancelled:
                self._set_status("Preview cancelled. No preview was created.")
                return ()
            except Exception as error:
                self._set_status(str(error), error=True)
                return ()

        def _create_result(self, selected):
            if self.source is None:
                self._set_status("Select exactly one object before creating a preview.", error=True)
                return ()
            try:
                if self._mode() == "semantic":
                    created = (
                        semantics.create_semantic_region_contour(
                            self.source,
                            role=self._role(),
                            reference_direction=self._direction(),
                            policy=self._policy(),
                            region_ids=None if selected is None else [result.region_id for result in selected],
                        ),
                    )
                else:
                    created = (
                        contours.create_parametric_region_contour(
                            self.source,
                            region_ids=None if selected is None else [result.region_id for result in selected],
                            policy=self._policy(),
                        ),
                    )
            except contours.ContourCancelled:
                raise
            except Exception as error:
                self._set_status("Preview creation failed: %s" % error, error=True)
                return ()
            Gui.Selection.clearSelection()
            for obj in created:
                Gui.Selection.addSelection(obj)
            status = created[0].ContourStatus
            if status not in ("ok", "partial"):
                self._set_status(
                    "Created parametric preview with status %s: %s"
                    % (status, created[0].Diagnostics or created[0].LastError),
                    error=True,
                )
            else:
                self._set_status(
                    "Created parametric contour preview; it follows source recomputes."
                )
            return created

        def create_selected(self):
            row = self.region_list.currentRow()
            if row < 0 or row >= len(self.results):
                self._set_status("Choose one detected region first.", error=True)
                return ()
            return self._create((self.results[row],))

        def create_all(self):
            return self._create(None)

        def accept(self):
            self.create_selected()

        def reject(self):
            self._closing = True
            if self._busy:
                self._cancel()
                return
            Gui.Control.closeDialog()


    class _SurfaceContoursCommand:
        def GetResources(self):
            return {
                "MenuText": "Surface contours",
                "ToolTip": "Detect semantic surface roles and create parametric contours",
                "Accel": "",
            }

        def Activated(self):
            Gui.Control.showDialog(SurfaceContourTaskPanel())

        def IsActive(self):
            return App.ActiveDocument is not None and len(Gui.Selection.getSelection()) == 1


    Gui.addCommand("Part_SurfaceContours", _SurfaceContoursCommand())
else:

    class SurfaceContourTaskPanel:
        """Placeholder that keeps the module importable in freecadcmd."""

        def __init__(self):
            raise RuntimeError("Surface contour task panel requires FreeCADGui")

