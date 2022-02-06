from urllib.parse import urljoin, parse_qs, urlparse

import constants


class URLS:

    def __init__(self):
        self.base_url = "https://www.jamstockex.com"

        self.listed_stocks_url = "/listings/listed-companies/?market={}"
        self.corporate_actions_url = "/trading/corporate-actions/?instrumentCode={}&fromDate={}&thruDate={}"
        self.trade_summary = "/trading/trade-quotes/?market={}&date={}"

    def _get_resource_url(self, resource_name):
        url_dict = {
            constants.LISTED_COMPANIES_RESOURCE: self.listed_stocks_url,
            constants.SUMMARY_RESOURCE: self.trade_summary,
            constants.CORPORATE_ACTION_RESOURCE: self.corporate_actions_url
        }

        return urljoin(self.base_url, url_dict[resource_name])

    def join_url(self, url_path):
        return urljoin(self.base_url, url_path)

    @staticmethod
    def get_query_param_value(url, query_param):
        parsed_url = urlparse(url)
        return parse_qs(parsed_url.query)[query_param][0]

    def get_formatted_resource_url(self, resource_name, *args):
        url = self._get_resource_url(resource_name)
        return url.format(*args)
