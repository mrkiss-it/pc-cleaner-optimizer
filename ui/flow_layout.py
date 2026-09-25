"""Wrapping row layout. Items stay readable and drop to the next line."""
from PyQt5.QtCore import QPoint, QRect, QSize, Qt
from PyQt5.QtWidgets import QLayout


class FlowLayout(QLayout):
    """Left-to-right layout that wraps instead of forcing a wider window.

    When every item fits on one line and ``expand`` is true, leftover width
    is shared so action bars still fill the row.
    """

    def __init__(self, parent=None, margin=0, h_spacing=8, v_spacing=8, expand=False):
        super().__init__(parent)
        self._items = []
        self._h_space = int(h_spacing)
        self._v_space = int(v_spacing)
        self._expand = bool(expand)
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, widget, stretch=0):
        if stretch:
            widget.setProperty("_flowStretch", int(stretch))
        super().addWidget(widget)

    def horizontalSpacing(self):
        return self._h_space

    def verticalSpacing(self):
        return self._v_space

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, max(0, int(width)), 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._visible_items():
            hint = item.minimumSize()
            # A single item must not demand the whole unwrapped row.
            size = size.expandedTo(QSize(min(hint.width(), self._widest_natural(item)), hint.height()))
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _visible_items(self):
        visible = []
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            visible.append(item)
        return visible

    def _widest_natural(self, item):
        widget = item.widget()
        natural = item.sizeHint().width()
        if widget is not None and widget.hasHeightForWidth():
            # Wrapped text can live in a narrow column; don't let the
            # single-line hint set the window's minimum width.
            floor = item.minimumSize().width()
            return max(48, min(natural, max(floor, 280)))
        return max(natural, item.minimumSize().width())

    def _item_box(self, item, max_width):
        hint = item.sizeHint()
        width = hint.width()
        height = hint.height()
        widget = item.widget()
        if max_width > 0 and width > max_width:
            width = max_width
            if widget is not None and widget.hasHeightForWidth():
                height = max(height, widget.heightForWidth(width))
        return width, max(1, height)

    def _stretch_of(self, item):
        widget = item.widget()
        if widget is None:
            return 1
        value = widget.property("_flowStretch")
        try:
            stretch = int(value)
        except (TypeError, ValueError):
            stretch = 0
        return stretch if stretch > 0 else 1

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        if area.width() < 0:
            area.setWidth(0)
        items = self._visible_items()
        if not items:
            return margins.top() + margins.bottom()

        max_width = area.width()
        space_x = self.horizontalSpacing()
        space_y = self.verticalSpacing()
        boxes = [self._item_box(item, max_width) for item in items]
        natural_width = sum(box[0] for box in boxes) + space_x * max(0, len(boxes) - 1)
        one_line = natural_width <= max_width and max_width > 0

        if one_line and self._expand and not test_only:
            extra = max_width - natural_width
            stretches = [self._stretch_of(item) for item in items]
            total_stretch = sum(stretches) or 1
            boxes = [
                (width + extra * stretch // total_stretch, height)
                for (width, height), stretch in zip(boxes, stretches)
            ]

        x = area.x()
        y = area.y()
        line_height = 0
        for item, (width, height) in zip(items, boxes):
            next_x = x + width + space_x
            if line_height > 0 and x > area.x() and (x + width) > area.right() + 1:
                x = area.x()
                y += line_height + space_y
                next_x = x + width + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, height)))
            x = next_x
            line_height = max(line_height, height)

        return y + line_height - rect.y() + margins.bottom()
