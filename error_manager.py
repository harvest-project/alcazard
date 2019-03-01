class Severity:
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'


class ErrorInfo:
    def __init__(self, severity, key, message, traceback):
        self.severity = severity
        self.key = key
        self.message = message
        self.traceback = traceback

    def to_dict(self):
        return dict(self.__dict__)


class ErrorManager:
    GREEN = 'green'  # All is good in the world
    YELLOW = 'yellow'  # Some warnings that need to be looked at
    RED = 'red'  # Something very bad happened

    def __init__(self):
        self._current_errors = {}

    @property
    def status(self):
        statuses = {error.severity for error in self._current_errors.values()}
        if Severity.ERROR in statuses:
            return self.RED
        elif Severity.WARNING in statuses:
            return self.YELLOW
        return self.GREEN

    def add_error(self, severity, key, message, traceback=None):
        self._current_errors[key] = ErrorInfo(
            severity=severity,
            key=key,
            message=message,
            traceback=traceback
        )

    def clear_error(self, key, convert_errors_to_warnings=True):
        if key in self._current_errors:
            if convert_errors_to_warnings:
                error = self._current_errors[key]
                if error.severity == Severity.ERROR:
                    self._current_errors[key] = ErrorInfo(
                        severity=Severity.WARNING,
                        key=key,
                        message='Error resolved to warning: '.format(error.message),
                        traceback=error.traceback,
                    )
            else:
                del self._current_errors[key]

    def to_dict(self):
        return dict(self._current_errors)
