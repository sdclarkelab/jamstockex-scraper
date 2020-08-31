import logging
import sys
import pytz

from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup as bS

import utils.parser
from utils import log, constants, urls


def extract_stock_info(market_parse_trees: [bS]) -> [{}]:
    """

    :param market_parse_trees:
    :return:
    """

    stock_info_list = list()

    try:

        for market_parse_tree in market_parse_trees:

            #  Get List and De-Listed stock tables
            table_parse_trees = _extract_market_tables(market_parse_tree)

            #  First table contains listed stocks
            is_listed_stock_table = True
            market_type = _extract_market_type(market_parse_tree)

            for table_parse_tree in table_parse_trees:
                stock_info_list.extend(_get_stocks(table_parse_tree, market_type, is_listed_stock_table))
                is_listed_stock_table = False

        return stock_info_list

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _extract_market_tables(parse_tree: bS) -> [bS]:
    try:
        tables = parse_tree.findAll('table', attrs={'class': 'table table-striped table-hover'})
        return tables

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _extract_market_type(parse_tree: bS) -> str:
    """

    :param bS parse_tree:
    :return:
    """
    try:
        market_type = str(parse_tree.find('h1').text).strip()

        return market_type

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _get_stocks(table_parse_tree: bS, market_type: str, is_listed: bool) -> [{}]:
    """

    :param table_parse_tree:
    :param is_listed:
    :return:
    """

    stocks = list()
    tz = pytz.timezone(constants.JA_TIMEZONE)

    try:

        for row in table_parse_tree.findAll('tr'):
            cells = row.findAll("td")

            if len(cells) == 6:
                stock = dict()

                stock[constants.LAST_UPDATED_DATE] = datetime.now(tz)
                stock[constants.INSTRUMENT_NAME] = utils.parser.extract_cell_value(cell=cells[0])
                stock[constants.SYMBOL] = utils.parser.extract_cell_value(cell=cells[1]).replace('%', '')
                stock[constants.CURRENCY] = utils.parser.extract_cell_value(cell=cells[2])
                stock[constants.SECTOR] = utils.parser.extract_cell_value(cell=cells[3])
                stock[constants.TYPE] = utils.parser.extract_cell_value(cell=cells[4])
                stock[constants.WEBSITE] = utils.parser.extract_cell_value(cell=cells[5], is_link=True)
                stock[constants.IS_LISTED] = is_listed
                stock[constants.MARKET] = market_type
                stock[constants.STOCK_CORPORATE_ACTION_URL] = urls.dividend_url.format(
                    stock[constants.SYMBOL])
                stock[constants.DIVIDENDS] = []
                stock[constants.TRADE_INFO] = {}

                stocks.append(stock)

        return stocks

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def extract_market_urls(parse_tree: bS, url: str) -> [str]:
    """

    :param parse_tree:
    :param str url:
    :return:
    """

    logging.info("Extract market urls ...")
    page_urls = []

    try:

        select = parse_tree.find('select', attrs={'name': 'Markets', 'id': 'markets'})

        #  Create market url
        for option in select.findAll('option'):
            page_url = urljoin(url, option['value'])
            page_urls.append(page_url)

        return page_urls

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
