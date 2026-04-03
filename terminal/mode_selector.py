"""Mode selector modal — startup screen for choosing asset class."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ModeSelectorModal(ModalScreen):
    """Landing screen: pick Stocks, Polymarket, or Crypto."""

    BINDINGS = [
        ("1", "select('stocks')", "Stocks"),
        ("2", "select('polymarket')", "Polymarket"),
        ("3", "select_disabled", "Crypto"),
        ("escape", "dismiss_modal", "Close"),
    ]

    DEFAULT_CSS = """
    ModeSelectorModal {
        align: center middle;
    }
    #mode-dialog {
        width: 52;
        height: 22;
        border: solid #ffb000;
        background: #111111;
        padding: 1 2;
    }
    .mode-btn {
        width: 100%;
        margin: 1 0;
        min-height: 3;
    }
    #btn-stocks {
        background: #003300;
        color: #00ff00;
        border: solid #00ff00;
    }
    #btn-stocks:hover {
        background: #005500;
    }
    #btn-polymarket {
        background: #001133;
        color: #00bbff;
        border: solid #00bbff;
    }
    #btn-polymarket:hover {
        background: #002255;
    }
    #btn-crypto {
        background: #1a1a1a;
        color: #666666;
        border: solid #333333;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="mode-dialog"):
            yield Label(
                "[#ffb000 bold]SELECT MODE[/]\n"
                "[#666666]Press 1, 2, or 3  —  or click[/]",
            )
            yield Button("[1]  STOCKS", id="btn-stocks", classes="mode-btn")
            yield Button("[2]  POLYMARKET", id="btn-polymarket", classes="mode-btn")
            yield Button("[3]  CRYPTO  (Coming Soon)", id="btn-crypto", classes="mode-btn", disabled=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-stocks":
            self.dismiss("stocks")
        elif event.button.id == "btn-polymarket":
            self.dismiss("polymarket")

    def action_select(self, asset_class: str) -> None:
        self.dismiss(asset_class)

    def action_select_disabled(self) -> None:
        self.notify("Crypto mode coming soon", severity="warning")

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)
