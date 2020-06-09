class CustomError(Exception):
    """Base class for exceptions in this module."""
    pass


class PageNotFoundError(CustomError):
    """Exception raised for errors in the input."""

    def __init__(self, msg=None):
        if msg is None:
            # Set some default useful error message
            msg = "Page Not Found!"
        super(CustomError, self).__init__(msg)


class TableNotFoundError(CustomError):
    """Exception raised for errors in the input."""

    def __init__(self, msg=None, table_name=None):
        if msg is None and table_name is None:
            # Set some default useful error message
            msg = "Table Not Found!"
        elif msg is None and table_name:
            msg = f'Table {table_name} Not Found!'

        super(CustomError, self).__init__(msg)
