# Created by Stephen Clarke at 09-Jul-19

import logging
import sys

from pymongo import MongoClient

import stock.db_crud_op
import stock.index_composition.parser as stock_index_composition_parser
import utils.parser
from utils import log, urls


def main(stock_info_col: MongoClient):
    logging.info("Starting Stock Index Composition Crawler ...")

    try:
        index_composition_parse_tree = utils.parser.get_parse_tree(urls.index_composition_url, timeout_retry_num=2)

        if index_composition_parse_tree:
            table_parse_tree = stock_index_composition_parser.extract_table_parse_tree(index_composition_parse_tree)

            index_composition_data = stock_index_composition_parser.extract_index_composition(table_parse_tree)

            stock.db_crud_op.update_stock_price_history(stock_info_col, index_composition_data)

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
