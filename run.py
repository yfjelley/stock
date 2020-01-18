import argparse
import threading
import time
from common import *
from tabulate import tabulate


class Trading(object):

    def __init__(self, fund):
        self.active = True
        self.fund = fund
        self.lock = threading.RLock()
        self.all_series = filter_low_volume_series(
            filter_garbage_series(get_all_series(MAX_HISTORY_LOAD)))
        self.thresholds = {}
        self.avg_returns = {}
        self.down_percents = {}
        self.prices = {}
        self.ordered_symbols = []
        dir_path = os.path.dirname(os.path.realpath(__file__))
        self.price_cache_file = os.path.join(dir_path, CACHE_DIR, get_business_day(0) + '-prices.json')

        read_cache = os.path.isfile(self.price_cache_file)
        if read_cache:
            with open(self.price_cache_file) as f:
                self.prices = json.loads(f.read())
        else:
            self.update_prices(self.all_series.keys(), use_tqdm=True)

        for ticker, series in self.all_series.items():
            _, avg_return, threshold = get_picked_points(series[-LOOK_BACK_DAY:])
            self.thresholds[ticker] = threshold
            self.avg_returns[ticker] = avg_return

        self.update_ordered_symbols()

        update_frequencies = [(10, 60), (100, 600), (len(self.ordered_symbols), 2400)]
        self.last_updates = {update_frequencies[-1][1]: datetime.datetime.now()} if not read_cache else {}

        for args in update_frequencies:
            t = threading.Thread(target=self.update_stats, args=args)
            t.daemon = True
            t.start()

    def update_stats(self, length, sleep_secs):
        while True:
            with self.lock:
                symbols = [symbol for symbol in self.ordered_symbols[:length]]
            self.update_prices(symbols)
            self.update_ordered_symbols()
            self.last_updates[sleep_secs] = datetime.datetime.now()
            time.sleep(sleep_secs)

    def update_prices(self, tickers, use_tqdm=False):
        threads = []
        with futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as pool:
            for ticker in tickers:
                 if not self.active:
                     return
                 t = pool.submit(get_real_time_price, ticker)
                 threads.append(t)
            iterator = tqdm(threads, ncols=80) if use_tqdm else threads
            for t in iterator:
                 if not self.active:
                     return
                 ticker, price = t.result()
                 if price:
                     self.prices[ticker] = price
        with self.lock:
            with open(self.price_cache_file, 'w') as f:
                f.write(json.dumps(self.prices))

    def update_ordered_symbols(self):
        tmp_ordered_symbols = []
        for ticker, series in self.all_series.items():
            if ticker not in self.prices:
                continue
            series = self.all_series[ticker]
            price = self.prices[ticker]
            down_percent = (np.max(series[-DATE_RANGE:]) - price) / np.max(series[-DATE_RANGE:])
            self.down_percents[ticker] = down_percent
            threshold = self.thresholds[ticker]
            tmp_ordered_symbols.append(ticker)
        tmp_ordered_symbols.sort(
            key=lambda ticker: min(np.abs(self.down_percents[ticker] - self.thresholds[ticker]),
                                   np.abs((self.all_series[ticker][-1] - price) / self.all_series[ticker][-1])
                                   + float(self.down_percents[ticker] < self.thresholds[ticker])))
        with self.lock:
            self.ordered_symbols = tmp_ordered_symbols

    def run(self):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        output_path = os.path.join(dir_path, OUTPUTS_DIR, get_business_day(0) + '.txt')
        output_file = open(output_path, 'a')
        while get_time_now() < 16:
            buy_symbols = []
            for ticker in self.ordered_symbols:
                series = self.all_series[ticker]
                is_buy = self.prices[ticker] < series[-1] and self.down_percents[ticker] > self.thresholds[ticker] > 0
                if is_buy:
                    buy_symbols.append((self.avg_returns[ticker], ticker))
            trading_list = get_trading_list(buy_symbols)
            bi_print(get_header(datetime.datetime.now().strftime('%H:%M:%S')), output_file)
            print_trading_list(trading_list, self.prices, self.down_percents, self.thresholds, self.all_series, self.fund, output_file)
            bi_print('Last updates: %s' % (
                [second_to_string(update_freq) + ': ' + update_time.strftime('%H:%M:%S')
                 for update_freq, update_time in
                 sorted(self.last_updates.items(), key=lambda t:t[0])],), output_file)
            time.sleep(100)
        self.active = False
        time.sleep(1)


def get_real_time_price(ticker):
    return _get_real_time_price_from_yahoo(ticker)


def _get_real_time_price_from_yahoo(ticker):
    url = 'https://finance.yahoo.com/quote/{}'.format(ticker)
    prefixes = ['"currentPrice"', '"regularMarketPrice"']
    try:
        price = float(web_scraping(url, prefixes))
    except Exception as e:
        print(e)
        price = None
    return ticker, price


def get_static_trading_table(fund=None):
    """"Gets stock symbols to buy from previous close."""
    all_series = filter_low_volume_series(
        filter_garbage_series(get_all_series(MAX_HISTORY_LOAD)))
    buy_symbols = get_buy_symbols(all_series, -1)
    trading_list = get_trading_list(buy_symbols)
    price_list = {ticker: all_series[ticker][-1] for ticker, _ in trading_list}
    down_percent_list = {ticker: (np.max(all_series[ticker][-1-DATE_RANGE:-1]) - all_series[ticker][-1]) / np.max(all_series[ticker][-1-DATE_RANGE:-1])
                         for ticker, _ in trading_list}
    threshold_list = {ticker: get_picked_points(all_series[ticker][-1-LOOK_BACK_DAY:-1])[2] for ticker, _ in trading_list}
    print_trading_list(trading_list, price_list, down_percent_list, threshold_list, all_series, fund)


def print_trading_list(trading_list, price_list, down_percent_list, threshold_list, all_series,
                       fund=None, output_file=None):
    trading_table = []
    cost = 0
    for ticker, proportion in trading_list:
        trading_row = [ticker, '%.2f%%' % (proportion * 100,)]
        price = price_list[ticker]
        change = (price - all_series[ticker][-1]) / all_series[ticker][-1]
        trading_row.extend(['%.2f%%' % (change * 100,),
                            '%.2f%%' % (-down_percent_list[ticker] * 100,),
                            '%.2f%%' % (-threshold_list[ticker] * 100,), price])
        if fund:
            value = fund * proportion
            n_shares = np.round(value / price)
            share_cost = n_shares * price
            cost += share_cost
            trading_row.extend([share_cost, n_shares])
        trading_table.append(trading_row)
    headers = ['Symbol', 'Proportion', 'Today Change', '%d Day Change' % (DATE_RANGE,), 'Threshold', 'Price']
    if fund:
        headers.extend(['Cost', 'Quantity'])
    if trading_table:
        bi_print(tabulate(trading_table, headers=headers, tablefmt='grid'), output_file)
        if fund:
            bi_print('Fund: %.2f' % (fund,), output_file)
            bi_print('Actual Cost: %.2f' % (cost,), output_file)


def get_live_trading_table(fund=None):
    """"Gets stock symbols to buy from previous close."""
    trading = Trading(fund)
    trading.run()


def second_to_string(secs):
    if secs < 60:
        return str(secs) + 's'
    elif secs < 3600:
        return str(secs // 60) + 'm'
    else:
        return str(secs // 3600) + 'h'


def main():
    parser = argparse.ArgumentParser(description='Stock trading strategy.')
    parser.add_argument('--fund', default=None, help='Total fund to trade.')
    parser.add_argument('--mode', default='live', choices=['live', 'static'], help='Mode to run.')
    args = parser.parse_args()
    fund = float(args.fund) if args.fund else None
    if args.mode == 'live':
        get_live_trading_table(fund)
    elif args.mode == 'static':
        get_static_trading_table(fund)
    else:
        raise Exception('Unknown mode')


if __name__ == '__main__':
    main()
