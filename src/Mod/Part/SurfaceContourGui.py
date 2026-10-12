# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI workflow for object-level surface contour extraction.

The command deliberately asks for one object, not a list of manually picked
faces.  Region detection and contour geometry remain in the GUI-independent
SurfaceRegions and SurfaceContours modules; this file only presents those
results and creates the requested snapshot previews.
"""

import FreeCAD as App

import SurfaceContours as contours
import SurfaceRegions as regions


def selected_document_object(selection):
    """Return the only selected document object, or ``None``.

    Keeping this small policy helper GUI-independent makes the selection
    contract testable in ``freecadcmd`` and prevents accidental face-level
    selection from entering the extraction API.
    """
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
                "no individual face picking is needed."
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
            self.create_button = QtWidgets.QPushButton("Create selected contour preview")
            self.create_button.clicked.connect(self.create_selected)
            self.create_all_button = QtWidgets.QPushButton("Create all previews")
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
                    "%d region(s) detected. Choose a row to create one contour preview."
                    % len(self.results)
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
                results, created = contours.create_region_contour_preview(
                    self.source, selected
                )
            except Exception as error:
                self._set_status("Preview creation failed: %s" % error, error=True)
                return ()
            if not created:
                self._set_status(
                    "No selected region has a valid physical boundary to preview.", error=True
                )
                return ()
            Gui.Selection.clearSelection()
            for obj in created:
                Gui.Selection.addSelection(obj)
            self._set_status("Created %d contour preview object(s)." % len(created))
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
            # The task-panel OK action is intentionally equivalent to creating
            # the currently selected preview, while the explicit buttons stay
            # available for creating one or all previews without closing.
            self.create_selected()

        def reject(self):
            Gui.Control.closeDialog()


    class _SurfaceContoursCommand:
        def GetResources(self):
            return {
                "MenuText": "Surface contours",
                "ToolTip": "Detect surface regions and create physical contour previews",
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

