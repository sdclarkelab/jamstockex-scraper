# Created by Stephen Clarke at 07-Jul-19

import locale
import logging
import sys
from datetime import datetime

import pytz
from bs4 import BeautifulSoup as bS

import utils.parser
from utils import log, custom_exception, constants


def extract_dividends(dividend_table_parse_tree: bS) -> {}:
    """
    Added list of dividends for a specific instrument.
    :param dividend_table_parse_tree:
    :return:
    """

    try:
        dividend_data = dict()
        #  Set currency
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')

        for row in dividend_table_parse_tree.findAll('tr'):
            cells = row.findAll("td")

            if len(cells) == 6:
                dividend_action = cells[2].find(text=True).strip()

                if dividend_action == 'Dividend':
                    dividend = dict()

                    dividend[constants.AMOUNT] = locale.atof(utils.parser.extract_cell_value(cells[5]))

                    payment_date = datetime.strptime(utils.parser.extract_cell_value(cells[4]), '%Y-%m-%d')
                    dividend[constants.PAYMENT_DUE] = pytz.utc.localize(payment_date)

                    execution_date = datetime.strptime(utils.parser.extract_cell_value(cells[3]), '%Y-%m-%d')
                    dividend[constants.EXECUTION_DATE] = pytz.utc.localize(execution_date)

                    record_date = datetime.strptime(utils.parser.extract_cell_value(cells[0]), '%Y-%m-%d')
                    dividend[constants.RECORD_DATE] = pytz.utc.localize(record_date)

                    symbol = utils.parser.extract_cell_value(cells[1])
                    dividend_data.setdefault(symbol, []).append(dividend)

            else:
                raise custom_exception.TableNotFoundError(table_name='Dividend')

        return dividend_data

    except custom_exception.PageNotFoundError as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except custom_exception.TableNotFoundError as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def extract_dividend_table_parse_tree(corporate_actions_parse_tree: bS) -> bS:
    try:

        dividend_table_parse_tree = corporate_actions_parse_tree.find_all('tbody')[0]

        return dividend_table_parse_tree

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
