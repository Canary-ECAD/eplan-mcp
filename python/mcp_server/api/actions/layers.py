"""
Layer management actions.
"""

from ._base import _get_connected_manager, _build_action


def change_layer(
    layer_name: str = None,
    visible: bool = None,
    printed: bool = None,
    text_height: float = None,
    color_id: int = None,
    transparency: float = None,
    project_name: str = None
) -> dict:
    """
    Change graphical layer properties.
    Action: changelayer

    Args:
        layer_name: Name of the layer (parameter LAYER).
        visible: Whether the layer is visible (parameter VISIBLE).
        printed: Whether the layer is printed (parameter PRINTED).
        text_height: Text height of the layer (parameter TEXTHEIGHT).
        color_id: Color ID of the layer (parameter COLORID).
        transparency: Transparency of the layer (parameter TRANSPARENCY).
        project_name: Project path (optional). If omitted, the selected
                      project is used.
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "changelayer",
        PROJECTNAME=project_name,
        LAYER=layer_name,
        VISIBLE=visible,
        PRINTED=printed,
        TEXTHEIGHT=text_height,
        COLORID=color_id,
        TRANSPARENCY=transparency
    )
    return manager.execute_action(action)


def export_graphical_layer_table(
    export_file: str,
    project_name: str = None
) -> dict:
    """
    Export graphical layer table.
    Action: graphicallayertable
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "graphicallayertable",
        TYPE="EXPORT",
        PROJECTNAME=project_name,
        EXPORTFILE=export_file
    )
    return manager.execute_action(action)


def import_graphical_layer_table(
    import_file: str,
    project_name: str = None
) -> dict:
    """
    Import graphical layer table.
    Action: graphicallayertable
    """
    manager, error = _get_connected_manager()
    if error:
        return error

    action = _build_action(
        "graphicallayertable",
        TYPE="IMPORT",
        PROJECTNAME=project_name,
        IMPORTFILE=import_file
    )
    return manager.execute_action(action)
