"""Project Path Resolver for StickmanHybrid.
Resolves slugs seamlessly across root, long_videos/, and shorts/ directories.
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_project_dir(slug_or_path):
    """Finds a project directory by name, whether inside long_videos/, shorts/, or direct path."""
    if not slug_or_path:
        return BASE_DIR

    # Absolute path check
    if os.path.isabs(slug_or_path) and os.path.exists(slug_or_path):
        return os.path.abspath(slug_or_path)

    # Direct path relative to current working directory
    if os.path.exists(slug_or_path):
        return os.path.abspath(slug_or_path)

    # Direct path relative to BASE_DIR (e.g. 'long_videos/nalanda' or 'shorts/werewolf')
    direct = os.path.join(BASE_DIR, slug_or_path)
    if os.path.exists(direct):
        return direct

    # Check inside long_videos/ (e.g. user just passed 'nalanda')
    long_p = os.path.join(BASE_DIR, "long_videos", slug_or_path)
    if os.path.exists(long_p):
        return long_p

    # Check inside shorts/ (e.g. user just passed 'dark_forest')
    short_p = os.path.join(BASE_DIR, "shorts", slug_or_path)
    if os.path.exists(short_p):
        return short_p

    # Fallback default for new project initialization
    clean_slug = slug_or_path.replace("\\", "/").strip("/")
    if clean_slug.startswith("long_videos/") or clean_slug.startswith("shorts/"):
        return os.path.join(BASE_DIR, clean_slug.replace("/", os.sep))
    if "short" in clean_slug.lower():
        return short_p
    return long_p


def get_relative_slug(full_project_dir):
    """Returns normalized relative slug path (e.g. 'long_videos/nalanda')."""
    return os.path.relpath(full_project_dir, BASE_DIR).replace("\\", "/")
