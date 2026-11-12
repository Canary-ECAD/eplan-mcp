"""
Translation actions.
"""

from ._base import _get_connected_manager, _build_action


def translate_project(project_name: str = None) -> dict:
    """
    Translate a project using the translation database.
    Action: translate
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "translate",
        TYPE="TRANSLATEPROJECT",
        PROJECTNAME=project_name
    )
    return manager.execute_action(action)


def export_missing_translations(
    export_file: str,
    language: str,
    project_name: str = None,
    converter: str = None
) -> dict:
    """
    Export missing translations list.
    Action: translate
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "translate",
        TYPE="EXPORTMISSINGTRANSLATIONS",
        PROJECTNAME=project_name,
        EXPORTFILE=export_file,
        LANGUAGE=language,
        CONVERTER=converter
    )
    return manager.execute_action(action)


def remove_language(language: str, project_name: str = None) -> dict:
    """
    Remove a language from project.
    Action: translate

    Args:
        language: Language code(s) to remove (e.g., "en_US" or "en_US,fr_FR")
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "translate",
        TYPE="REMOVELANGUAGE",
        PROJECTNAME=project_name,
        LANGUAGE=language
    )
    return manager.execute_action(action)
