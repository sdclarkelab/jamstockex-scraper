# Created by Stephen Clarke at 09-Jul-19

import locale
import logging
import sys
from datetime import datetime

import pytz
from bs4 import BeautifulSoup as bS

from utils import log, constants


def extract_ticker_data(ticker_parse_tree: bS) -> {}:
    """

    :param ticker_parse_tree:
    :return:
    """
    ticker_data = dict()

    try:

        #  MUST remain in this order
        ticker_status = _extract_ticker_status(ticker_parse_tree)
        ticker_header = _extract_ticker_header(ticker_parse_tree)
        ticker_datetime = _extract_ticker_datetime(ticker_header, ticker_status)

        # checks if the stock market is live
        if ticker_status == constants.LIVE:
            ticker_data = _live_ticker_parser(ticker_parse_tree, ticker_datetime, ticker_status)

        if ticker_status == constants.SUMMARY:
            ticker_data = _summary_ticker_parser(ticker_parse_tree, ticker_status)

        return ticker_data

    except ValueError as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _extract_ticker_header(ticker_parse_tree: bS) -> str:
    """

    :param bS ticker_parse_tree:
    :return:
    """
    ticker_header = None

    try:

        for li_tag in ticker_parse_tree.findAll('li', {'class': 'live-ticker-heading'}):
            ticker_header = li_tag.text.strip()

        logging.debug(f'JSE Ticker Header - "{ticker_header}"')

        return ticker_header

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _extract_ticker_datetime(jse_ticker_header: str, jse_ticker_status: str) -> datetime:
    """

    :param str jse_ticker_header:
    :return:
    """

    try:

        datetime_str = jse_ticker_header.split("for")[1].strip()

        if jse_ticker_status == constants.LIVE:
            ticker_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %I:%M %p')
        else:
            ticker_datetime = datetime.strptime(datetime_str, '%Y-%m-%d')

        logging.debug(f'JSE Ticker DateTime - "{ticker_datetime}"')

        return ticker_datetime

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _extract_ticker_status(ticker_parse_tree: bS) -> str:
    """

    :param bS ticker_parse_tree:
    :return:
    """
    try:
        trade_status = ticker_parse_tree.li.input['value']
        logging.info(f'JSE Ticker Status - "{trade_status}"')

        return trade_status

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _live_ticker_parser(ticker_parse_tree: bS, ticker_datetime: datetime, ticker_status: str):
    """stock

    :param Bs ticker_parse_tree:
    :param datetime ticker_datetime:
    :return:
    """
    ticker_data = {}

    try:

        #  Iterates over a tags that contains stock trade information
        for a_tag in ticker_parse_tree.find_all('a'):

            #  get symbol and trade time
            symbol, trade_time = _extract_live_symbol_and_trade_time(a_tag)

            #  Ignore symbols with the word "Index"
            if "Index" not in symbol:
                stock_trade_time = datetime.strptime(trade_time, '%H:%M:%S')
                date_time = datetime.combine(ticker_datetime.date(), stock_trade_time.time(), tzinfo=pytz.UTC)

                volume = _extract_volume(a_tag)
                market_price = _extract_market_price(a_tag)
                traded_price_change = _extract_price_change(a_tag)

                ticker = _create_ticker_data(volume, market_price, traded_price_change, ticker_status, date_time)

                ticker_data.setdefault(symbol, {}).update(ticker)

        return ticker_data

    except (TypeError, ValueError, IndexError) as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _summary_ticker_parser(ticker_parse_tree: bS, ticker_status: str):
    """

    :param bs ticker_parse_tree:
    :return:
    """
    ticker_data = {}

    try:
        for a_tag in ticker_parse_tree.find_all('a'):

            symbol = a_tag.contents[0].strip()  # get symbol

            if "Index" not in symbol:
                volume = _extract_volume(a_tag)
                market_price = _extract_market_price(a_tag)
                traded_price_change = _extract_price_change(a_tag)

                ticker = _create_ticker_data(volume=volume, market_price=market_price,
                                             traded_price_change=traded_price_change, ticker_status=ticker_status)
                ticker_data.setdefault(symbol, {}).update(ticker)

        return ticker_data
    except (TypeError, ValueError, IndexError) as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _extract_live_symbol_and_trade_time(a_tag: bS) -> (str, str):
    try:

        symbol, trade_time = a_tag.contents[0].strip().replace(" ", "").replace("\n", "").split("at")
        return symbol, trade_time

    except (TypeError, ValueError, IndexError) as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _extract_volume(a_tag: bS) -> int:
    try:
        volume = locale.atoi(a_tag.contents[2].replace("Vol", "").replace(",", "").strip())
        return volume

    except (TypeError, ValueError, IndexError) as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _extract_market_price(a_tag: bS) -> float:
    try:
        market_price = locale.atof(a_tag.contents[4].replace(",", "").replace("$", "").strip())
        return market_price

    except (TypeError, ValueError, IndexError) as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _extract_price_change(a_tag: bS) -> float:
    try:
        price_change = locale.atof(a_tag.contents[6].strip())
        return price_change

    except (TypeError, ValueError, IndexError) as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _create_ticker_data(volume: int, market_price: float, traded_price_change: float,
                        ticker_status: str, date_time: datetime = None) -> {}:
    ticker = dict()

    # ticker[constants.STATUS] = ticker_status
    ticker[constants.VOLUME] = volume
    ticker[constants.DOLLAR_CHANGE] = traded_price_change
    ticker[constants.MARKET_PRICE] = market_price
    ticker[constants.PERCENT_CHANGE] = 0
    # ticker[constants.TRADE_TIME] = date_time

    return ticker
