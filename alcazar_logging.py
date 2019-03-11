import inspect
import logging


class BraceMessage(object):
    def __init__(self, fmt, args, kwargs):
        self.fmt = fmt
        self.args = args
        self.kwargs = kwargs

    def __str__(self):
        return str(self.fmt).format(*self.args, **self.kwargs)


class BraceAdapter(logging.LoggerAdapter):
    def __init__(self, logger):
        super().__init__(logger, None)

    def log(self, level, msg, *args, **kwargs):
        if self.isEnabledFor(level):
            msg, log_kwargs = self.process(msg, kwargs)
            self.logger._log(
                level,
                BraceMessage(msg, args, kwargs),
                (),
                **log_kwargs,
            )

    def process(self, msg, kwargs):
        return msg, {key: kwargs[key]
                     for key in inspect.getfullargspec(self.logger._log).args[1:]
                     if key in kwargs}


def configure_logging(log_level):
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    peewee_logger = logging.getLogger('peewee')
    peewee_logger.setLevel(max(logging.INFO, log_level))  # We don't want peewee queries
