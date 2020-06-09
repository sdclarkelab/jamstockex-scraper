# Created by Stephen Clarke at 07-Jul-19

import logging
import sys

from pymongo import MongoClient

import stock.db_crud_op
import utils.parser
from stock.stock_info import parser as stock_info_parser
from utils import urls, log


def main(stock_info_col: MongoClient):
    """

    :return:
    """
    try:

        logging.info("Starting Stock Info Crawler ...")

        #  Gets listed companies parse tree
        company_list_parse_tree = utils.parser.get_parse_tree(urls.listed_compaines_url, timeout_retry_num=2)

        if company_list_parse_tree:

            # ******************** EXTRACT STOCK INFO **********************
            #  Get list of markets urls from drop down list
            market_urls = stock_info_parser.extract_market_urls(company_list_parse_tree, urls.listed_compaines_url)

            #  Get parse tree for each market page
            market_parse_trees = []
            for market_url in market_urls:
                market_parse_trees.append(utils.parser.get_parse_tree(url=market_url, timeout_retry_num=3))

            #  Extract stock info from market page content
            stock_info_list = stock_info_parser.extract_stock_info(market_parse_trees)

            # ******************** INSERT STOCK DATA **********************
            stock.db_crud_op.update_stock_info(stock_info_col, stock_info_list)

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
