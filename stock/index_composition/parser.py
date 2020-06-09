# Created by Stephen Clarke at 09-Jul-19

import locale
import logging
import sys
from datetime import datetime

from bs4 import BeautifulSoup as bS

import utils.parser
from utils import log, custom_exception, constants


def extract_table_parse_tree(index_composition_parse_tree: bS) -> bS:
    try:

        logging.info("Extracting Index Composition Table ...")
        table_parse_tree = index_composition_parse_tree.find_all('tbody')[0]

        return table_parse_tree

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def extract_index_composition(table_parse_tree: bS) -> {}:
    """
    Added list of dividends for a specific instrument.
    :param table_parse_tree:
    :return:
    """

    #  Set currency
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')

    try:

        index_composition_data = dict()

        #  Iterate over rows in the table
        for row in table_parse_tree.findAll('tr'):

            #  Validate that the table has 15 columns and extract their values
            cells = row.findAll("td")
            if len(cells) == 5:

                #  Create dictionary to store a symbols price history dictionary
                #  Example => {'CCC': {'volume_traded': 5, 'dollar_change': 1.50, ......}}
                symbol = utils.parser.extract_cell_value(cells[0], True, True)
                index_composition = dict()

                index_composition[constants.VOLUME] = locale.atoi(utils.parser.extract_cell_value(cells[4]))
                index_composition[constants.DOLLAR_CHANGE] = locale.atof(utils.parser.extract_cell_value(cells[2]))
                index_composition[constants.MARKET_PRICE] = locale.atof(utils.parser.extract_cell_value(cells[1]))
                index_composition[constants.PERCENT_CHANGE] = locale.atof(
                    utils.parser.extract_cell_value(cells[3]).replace("%", ""))
                index_composition[constants.LAST_UPDATED_DATE] = datetime.now()

                index_composition_data.setdefault(symbol, {}).update(index_composition)
            else:
                raise custom_exception.TableNotFoundError(table_name='Price History')

        return index_composition_data

    except custom_exception.PageNotFoundError as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except custom_exception.TableNotFoundError as e:
        logging.error(log.get_error_msg(e))
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
