"""Checker for calls to logger.exception with `stack: True`."""

import astroid
from astroid.node_classes import ExceptHandler

from pylint.checkers import BaseChecker, utils
from pylint.interfaces import IAstroidChecker


def register(linter):
    """Register checker."""
    linter.register_checker(SentryStackChecker(linter))


def complete_logging_methods(logging_methods):
    # Convert logging methods list to a set
    logging_methods_set = set(logging_methods)

    # Add both warn and warning, if at least one of them is included
    warning_methods = set(['warn', 'warning'])
    if logging_methods_set & warning_methods:
        logging_methods_set |= warning_methods

    return logging_methods_set


# from pylint/pylint/checkers/logging.py
def is_logger_class(node):
    try:
        for inferred in node.func.infer():
            if isinstance(inferred, astroid.BoundMethod):
                parent = inferred._proxied.parent
                if (
                    isinstance(parent, astroid.ClassDef) and
                    (
                        parent.qname() == 'logging.Logger' or
                        any(
                            ancestor.qname() == 'logging.Logger'
                            for ancestor in parent.ancestors()
                        )
                    )
                ):
                    return True
    except astroid.exceptions.InferenceError:
        pass
    return False


def includes_extra_stack(node):
    try:
        extra = utils.get_argument_from_call(node, keyword='extra')
    except utils.NoSuchArgumentError:
        return False

    for inferred in extra.inferred():
        if isinstance(inferred, astroid.Dict):
            for key, value in inferred.items:
                if key.value == 'stack' and value.value:
                    return True
    return False


def includes_exc_info(node):
    try:
        exc_info = utils.get_argument_from_call(node, keyword='exc_info')
    except utils.NoSuchArgumentError:
        return False
    return bool(exc_info.value)


def in_except_handler(node):
    parent = node.parent
    if parent is None:
        return False

    if isinstance(parent, ExceptHandler) and parent.name is not None:
        return True

    return in_except_handler(parent)


class SentryStackChecker(BaseChecker):
    """
    Looks for logging calls inside exception handlers, and suggest they
    include ``exc_info=True``, or change ``extra={'stack': True}`` to
    ``exc_info=True`` to get the stack from the exception instead of the one
    from the log statement.
    """

    __implements__ = (IAstroidChecker,)

    name = 'sentry-stack-checker'

    ADD_EXC_INFO = 'exc-log-add-exc-info'
    CHANGE_TO_EXC_INFO = 'exc-log-change-to-exc-info'
    msgs = {
        'R9501': (
            "Consider changing `'stack': True` to `exc_info=True`",
            CHANGE_TO_EXC_INFO,
            None,
        ),
        'R9502': (
            "Consider adding `exc_info=True`",
            ADD_EXC_INFO,
            None,
        ),
    }
    options = (
        (
            'report-loggers',
            {
                'default': 'debug,info,warning,error',
                'type': 'csv',
                'metavar': '<logging methods>',
                'help': 'List of logging methods that should generate messages',
            },
        ),
    )

    def set_option(self, optname, *args, **kwargs):
        super(SentryStackChecker, self).set_option(optname, *args, **kwargs)

        # Update complete logging methods to report
        if optname == 'report-loggers':
            self.logging_methods_to_report = complete_logging_methods(self.config.report_loggers)

    @utils.check_messages(ADD_EXC_INFO, CHANGE_TO_EXC_INFO)
    def visit_call(self, node):
        """Called for every function call in the source code."""

        if not isinstance(node.func, astroid.Attribute):
            # we are looking for method calls
            return

        if node.func.attrname not in self.logging_methods_to_report:
            return

        if not is_logger_class(node):
            return

        if not in_except_handler(node):
            return

        if includes_exc_info(node):
            return

        if not includes_extra_stack(node):
            self.add_message(self.ADD_EXC_INFO, node=node)
        else:
            self.add_message(self.CHANGE_TO_EXC_INFO, node=node)

    # compat for astroid < 1.4.0
    visit_callfunc = visit_call
