"""HTML element tree shared by the providers that scrape a rendered page."""

from __future__ import annotations

from collections.abc import Iterator
from html.parser import HTMLParser


class Node:
    """A single element in a parsed HTML document tree."""

    def __init__(
        self,
        tag: str = "",
        attrs: list[tuple[str, str | None]] = (),
        parent: Node | None = None,
    ) -> None:
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children: list[Node | str] = []

    def walk(self) -> Iterator[Node]:
        """Yield this node and all of its descendants in document order."""
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self) -> str:
        """Return the concatenated text content of this node."""
        return "".join(
            child.text() if isinstance(child, Node) else child
            for child in self.children
        )

    def has_class(self, name: str) -> bool:
        """Return whether this node carries the given CSS class."""
        classes = self.attrs.get("class") or ""
        return name in classes.split()


class _Document(HTMLParser):
    """Parse HTML into a tree of :class:`Node` objects."""

    VOID = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_html(markup: str | bytes) -> Node:
    """Return the root of a parsed HTML document.

    Args:
        markup: The document as text or as UTF-8 encoded bytes.

    Returns:
        The root :class:`Node`, whose :meth:`Node.walk` covers every element.
    """
    document = _Document()
    document.feed(markup.decode("utf-8") if isinstance(markup, bytes) else markup)
    return document.root
