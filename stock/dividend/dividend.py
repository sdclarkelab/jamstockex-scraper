# Created by Stephen Clarke at 07-Jul-19

import logging
import sys

from pymongo import MongoClient

import stock.db_crud_op
import stock.dividend.parser as stock_dividend_parser
import utils.parser
from utils import log, urls


def main(stock_info_col: MongoClient):
    logging.info("Starting Stock Dividend Crawler ...")

    try:

        #  Get corporate actions url to with start and end date
        corporate_actions_parse_tree = utils.parser.get_parse_tree(urls.corporate_url, timeout_retry_num=2)

        if corporate_actions_parse_tree:
            dividend_table_parse_tree = stock_dividend_parser.extract_dividend_table_parse_tree(
                corporate_actions_parse_tree)

            dividend_data = stock_dividend_parser.extract_dividends(dividend_table_parse_tree)

            stock.db_crud_op.update_stock_dividend(stock_info_col, dividend_data)

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
