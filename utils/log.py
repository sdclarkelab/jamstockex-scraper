# Created by Stephen Clarke at 07-Jul-19

import logging.config
import sys

import utils.urls


def setup_logger():
    try:
        logging_config_path = utils.urls.logging_config_path
        logging.config.fileConfig(logging_config_path, disable_existing_loggers=False)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger('root')
    except Exception as e:
        print(e)


def get_error_msg(msg):
    exception = sys.exc_info()
    return "{0} || LINE - {1} || {2}".format(exception[0], exception[2].tb_lineno, msg)
