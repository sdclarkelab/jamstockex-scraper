import logging


def setup_custom_logger(name):
    logger = logging.getLogger(name)

    c_handler = logging.StreamHandler()
    f_handler = logging.FileHandler('jamstockex.log')
    c_handler.setLevel(logging.DEBUG)
    f_handler.setLevel(logging.ERROR)

    # Create formatters and add it to handlers
    c_format = logging.Formatter('%(module)s - %(levelname)s - %(message)s')
    f_format = logging.Formatter('%(asctime)s - %(module)s - %(levelname)s - %(message)s')
    c_handler.setFormatter(c_format)
    f_handler.setFormatter(f_format)

    # Add handlers to the logger
    logger.addHandler(c_handler)
    logger.setLevel(logging.DEBUG)
    # logger.addHandler(f_handler)

    return logger
