class RolePermissionError(Exception):
    """
    Excepción lanzada cuando un usuario no tiene el rol necesario.
    El manejo de respuesta (JSON vs HTML) se hace en el ExceptionHandler.
    """
    def __init__(self, message: str = "No tienes permisos para realizar esta acción."):
        self.message = message