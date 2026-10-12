# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI workflow for object-level parametric surface contour extraction.

The command deliberately asks for one object, not a list of manually picked
faces. Region detection and contour geometry remain in the GUI-independent
SurfaceRegions and SurfaceContours modules; this file presents those results
and creates linked, recomputable preview features.
"""

import FreeCAD as App

import SurfaceContours as contours
import SurfaceRegions as regions


def selected_document_object(selection):
    """Return the only selected document object, or ``None``."""
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
        """Task panel for selecting a detected region after object selection."""

        def __init__(self):
            self.source = None
            self.detection = None
            self.results = ()
            self._building = False

            self.form = QtWidgets.QWidget()
            self.form.setWindowTitle("Surface contours")
            layout = QtWidgets.QVBoxLayout(self.form)

            intro = QtWidgets.QLabel(
                "Select one object in the model tree. Regions are detected automatically; "
                "no individual face picking is needed. Created previews stay linked to "
                "the source and update on recompute."
            )
            intro.setWordWrap(True)
            layout.addWidget(intro)

            source_row = QtWidgets.QHBoxLayout()
            source_row.addWidget(QtWidgets.QLabel("Object:"))
            self.source_edit = QtWidgets.QLineEdit()
            self.source_edit.setReadOnly(True)
            source_row.addWidget(self.source_edit, 1)
            self.refresh_button = QtWidgets.QPushButton("Refresh selection")
            self.refresh_button.clicked.connect(self.refresh)
            source_row.addWidget(self.refresh_button)
            layout.addLayout(source_row)

            policy_row = QtWidgets.QHBoxLayout()
            policy_row.addWidget(QtWidgets.QLabel("Grouping:"))
            self.policy_combo = QtWidgets.QComboBox()
            self.policy_combo.addItem("Coplanar connected regions", "coplanar")
            self.policy_combo.addItem("Every individual face", "individual")
            self.policy_combo.currentIndexChanged.connect(self.refresh)
            policy_row.addWidget(self.policy_combo, 1)
            layout.addLayout(policy_row)

            self.region_list = QtWidgets.QListWidget()
            self.region_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            self.region_list.currentRowChanged.connect(self._region_changed)
            layout.addWidget(self.region_list, 1)

            self.detail_label = QtWidgets.QLabel("No region selected.")
            self.detail_label.setWordWrap(True)
            layout.addWidget(self.detail_label)

            actions = QtWidgets.QHBoxLayout()
            self.create_button = QtWidgets.QPushButton("Create parametric preview")
            self.create_button.clicked.connect(self.create_selected)
            self.create_all_button = QtWidgets.QPushButton("Create all parametric previews")
            self.create_all_button.clicked.connect(self.create_all)
            actions.addWidget(self.create_button)
            actions.addWidget(self.create_all_button)
            layout.addLayout(actions)

            self.status_label = QtWidgets.QLabel()
            self.status_label.setWordWrap(True)
            layout.addWidget(self.status_label)
            self.refresh()

        def getStandardButtons(self):
            return int(QtGui.QDialogButtonBox.Close)

        def _policy(self):
            return self.policy_combo.currentData()

        def _set_status(self, text, error=False):
            self.status_label.setText(text)
            colour = "#a33" if error else "#555"
            self.status_label.setStyleSheet("color: %s" % colour)

        def refresh(self):
            self._building = True
            try:
                selection = Gui.Selection.getSelection()
                self.source = selected_document_object(selection)
                self.detection = None
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
                    self.detection = regions.detect_surface_regions(
                        self.source, policy=self._policy()
                    )
                    self.results = contours.extract_region_contours(
                        self.source, self.detection
                    )
                except Exception as error:
                    self._set_status("Contour detection failed: %s" % error, error=True)
                    self.create_button.setEnabled(False)
                    self.create_all_button.setEnabled(False)
                    return

                for result in self.results:
                    item = QtWidgets.QListWidgetItem(
                        "%s · %s · %d face(s) · %s"
                        % (
                            result.region_id,
                            result.component_id,
                            len(result.face_indices),
                            result.status,
                        )
                    )
                    item.setData(_USER_ROLE, result.region_id)
                    self.region_list.addItem(item)
                if self.results:
                    self.region_list.setCurrentRow(0)
                self.create_button.setEnabled(bool(self.results))
                self.create_all_button.setEnabled(bool(self.results))
                self._set_status(
                    "%d region(s) detected. Created previews will update when the source "
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
            self.detail_label.setText(
                "%s: %d boundary wire(s), %d face(s). Diagnostics: %s"
                % (result.status, len(result.wires), len(result.face_indices), diagnostic)
            )

        def _create(self, selected):
            if self.source is None:
                self._set_status("Select exactly one object before creating a preview.", error=True)
                return ()
            try:
                created = (
                    contours.create_parametric_region_contour(
                        self.source,
                        region_ids=[result.region_id for result in selected],
                        policy=self._policy(),
                    ),
                )
            except Exception as error:
                self._set_status("Preview creation failed: %s" % error, error=True)
                return ()
            Gui.Selection.clearSelection()
            for obj in created:
                Gui.Selection.addSelection(obj)
            status = created[0].ContourStatus
            if status in ("error", "missing_source", "no_region", "no_boundary"):
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
            return self._create(self.results)

        def accept(self):
            self.create_selected()

        def reject(self):
            Gui.Control.closeDialog()


    class _SurfaceContoursCommand:
        def GetResources(self):
            return {
                "MenuText": "Surface contours",
                "ToolTip": "Detect surface regions and create parametric contour previews",
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
