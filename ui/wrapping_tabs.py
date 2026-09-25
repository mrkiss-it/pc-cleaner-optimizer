"""Tab strip that wraps onto extra rows instead of scrolling sideways."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QPushButton, QSizePolicy, QWidget

from ui.flow_layout import FlowLayout


class WrappingTabBar(QWidget):
    """Visible stand-in for QTabBar. The native bar is hidden so it cannot
    show left/right scroll buttons when Vietnamese labels are wider than
    the window.
    """

    def __init__(self, tabs, parent=None):
        super().__init__(parent)
        self.setObjectName("MainTabStrip")
        self._tabs = tabs
        self._buttons = []
        self._flow = FlowLayout(self, margin=0, h_spacing=4, v_spacing=4, expand=False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        native = tabs.tabBar()
        # Keep scroll-button mode so the hidden bar's minimum width stays small.
        # Turning scroll buttons off makes Qt demand the full unwrapped tab row.
        native.setUsesScrollButtons(True)
        native.hide()
        native.setMaximumHeight(0)
        tabs.currentChanged.connect(self.sync)
        self.rebuild()

    def rebuild(self):
        while self._flow.count():
            item = self._flow.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._buttons = []
        for index in range(self._tabs.count()):
            button = QPushButton(self._tabs.tabText(index))
            button.setObjectName("navTab")
            button.setCursor(Qt.PointingHandCursor)
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setDefault(False)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _checked=False, idx=index: self._tabs.setCurrentIndex(idx))
            self._flow.addWidget(button)
            self._buttons.append(button)
        self.sync(self._tabs.currentIndex())

    def sync(self, index):
        for i, button in enumerate(self._buttons):
            button.setChecked(i == index)
