"""待办看板（兼容入口）。实现已迁到 cards.py。"""
from .cards import build_todos_card as build_board_card

__all__ = ["build_board_card"]
