# Created by Stephen Clarke at 09-Jul-19

import logging
import sys

from pymongo import MongoClient

import stock.db_crud_op
import stock.live_trade.parser as live_trade_parser
import utils.parser
from utils import log, urls


def main(stock_info_col: MongoClient):
    logging.info("Starting Ticker Crawler ...")

    try:
        ticker_parse_tree = utils.parser.get_parse_tree(urls.ticker_url, timeout_retry_num=2)

        if ticker_parse_tree:
            ticker_data = live_trade_parser.extract_ticker_data(ticker_parse_tree)
            stock.db_crud_op.update_trade_info(stock_info_col, ticker_data)

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
