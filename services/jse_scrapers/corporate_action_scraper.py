import logging

import constants
import helper
from urls import URLS

logger = logging.getLogger('root')
urls = URLS()


def get_corporate_actions(instrument_code, start_date, current_date, retry_num):
    try:
        url = urls.get_formatted_resource_url(constants.CORPORATE_ACTION_RESOURCE, instrument_code, start_date,
                                              current_date)

        parse_tree = helper.get_parse_tree(url, retry_num)

        corporate_actions_data = _extract_corporate_actions(parse_tree)

        return corporate_actions_data
    except Exception:
        raise


def _extract_corporate_actions(parse_tree):
    corporate_action_data = dict()
    table = helper.find_tables(parse_tree)

    for row in table.findAll('tr')[1:]:
        unformatted_cells = row.findAll("td")
        cells = helper.Cells(unformatted_cells)

        action = cells.extract_text(2)
        instrument = cells.extract_text(1)
        amount_str = unformatted_cells[5].text.replace("\n", "").strip().split(" ")
        instrument_code = f"{instrument.lower()}-{amount_str[0].lower()}"

        data = {
            constants.LAST_UPDATED_DATE: helper.get_current_time(),
            constants.RECORD_DATE: cells.extract_text(0),
            constants.EXECUTION_DATE: cells.extract_text(3),
            constants.PAYMENT_DUE: cells.extract_text(4),
            constants.AMOUNT: amount_str[-1]
        }

        corporate_action_data.setdefault(instrument_code, {}).setdefault(action, []).append(data)

    return corporate_action_data
