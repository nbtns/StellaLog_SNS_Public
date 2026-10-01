from __future__ import annotations


X_FIRST_HEADER = "【1つ目の投稿】"
X_SECOND_HEADER = "【2つ目の投稿】"


def format_x_thread(first_post: str, second_post: str) -> str:
    return (
        f"{X_FIRST_HEADER}\n{first_post.strip()}\n\n"
        f"{X_SECOND_HEADER}\n{second_post.strip()}"
    )


def split_x_thread(thread: str) -> tuple[str, str]:
    """Return both X posts, while keeping old one-post history readable."""

    text = thread.strip()
    marker = f"\n\n{X_SECOND_HEADER}\n"
    if text.startswith(f"{X_FIRST_HEADER}\n") and marker in text:
        first, second = text.removeprefix(f"{X_FIRST_HEADER}\n").split(marker, 1)
        return first.strip(), second.strip()
    return text, ""
