import json
import concurrent.futures
import logging
import datetime
import cProfile
import struct
import base64
from itertools import groupby
from bs4 import BeautifulSoup
import xxhash
from celery import Task
import urllib3
import redis
from simhash import Simhash
from surt import surt
from memory_profiler import profile
import gc
import sys
from celery.contrib import rdb
from pympler import asizeof

# https://urllib3.readthedocs.io/en/latest/advanced-usage.html#ssl-warnings
urllib3.disable_warnings()


class Discover(Task):
    """Custom Celery Task class.
    http://docs.celeryproject.org/en/latest/userguide/tasks.html#custom-task-classes
    """
    name = 'Discover'
    task_id = None

    def __init__(self, cfg):
        self.simhash_size = cfg['simhash']['size']
        # self.http = urllib3.PoolManager(retries=urllib3.Retry(3, redirect=1))
        redis_host = cfg['redis']['host']
        redis_port = cfg['redis']['port']
        redis_db = cfg['redis']['db']
        logfile = cfg['logfile']['name']
        loglevel = cfg['logfile']['level']
        self.thread_number = cfg['threads']
        self.snapshots_number = cfg['snapshots']['number_per_year']
        self.redis_db = redis.StrictRedis(host=redis_host, port=redis_port, db=redis_db)
        # self.http = urllib3.HTTPConnectionPool('web.archive.org', maxsize=8, retries=3, block=True)
        self.digest_dict = {}
        # Initialize logger
        self._log = logging.getLogger(__name__)
        logging.getLogger(__name__).setLevel(loglevel)
        logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s %(message)s',
                            handlers=[
                                logging.FileHandler(logfile),
                                logging.StreamHandler()
                            ])

    def timestamp_simhash(self, url, timestamp):
        if not url:
            # self._log.error('did not give url parameter')
            return json.dumps({'error': 'URL is required.'})
        if not timestamp:
            # self._log.error('did not give timestamp parameter')
            return json.dumps({'error': 'Timestamp is required.'})
        # self._log.info('requesting redis db entry for %s %s', url, timestamp)
        results = self.redis_db.hget(surt(url), timestamp)
        if results:
            results = results.decode('utf-8')
            # self._log.info('found entry %s', results)
            return json.dumps({'simhash': results})
        # self._log.info('entry not found')
        return json.dumps({'simhash': 'None'})

    def year_simhash(self, url, year):
        if not url:
            self._log.error('did not give url parameter')
            return json.dumps({'error': 'URL is required.'})
        if not year:
            self._log.error('did not give year parameter')
            return json.dumps({'error': 'Year is required.'})
        self._log.info('requesting redis db entry for %s %s', url, year)
        results = self.redis_db.hkeys(surt(url))
        if results:
            available_simhashes = []
            timestamps_to_fetch = []
            for timestamp in results:
                timestamp = timestamp.decode('UTF-8')
                timestamp_year = timestamp[:4]
                if timestamp_year == str(year):
                    timestamps_to_fetch.append(timestamp)
                    self._log.info('found entry %s', timestamp)
            if timestamps_to_fetch:
                results = self.redis_db.hmget(surt(url), timestamps_to_fetch)
                for i, simhash in enumerate(results):
                    available_simhashes.append([str(timestamps_to_fetch[i]), simhash.decode('utf-8')])
                return json.dumps(available_simhashes, separators=',:')
        self._log.info('No simhases for this URL and Year')
        return json.dumps({'simhash': 'None'})

    def download_snapshot(self, snapshot, url, i, total, job_id):
        # self._log.info('fetching snapshot %d out of %d', i, total)
        if (i-1) % 10 == 0:
            self.update_state(task_id=job_id, state='PENDING',
                          meta={'info': str(i - 1) + ' captures have been processed'})
        try:
            http = urllib3.PoolManager()
            response1 = http.request('GET', 'web.archive.org/web/' +snapshot[0] + 'id_/' + url)
            # self._log.info('calculating simhash for snapshot %d out of %d', i, total)
            return response1
        except urllib3.exceptions:
            return None
            # self._log.error(exc.args[0])

    def start_profiling(self, snapshot,
                        url, index, total, job_id):
        cProfile.runctx('self.get_calc_save(snapshot, url, index, total, job_id)',
                        globals=globals(), locals=locals(), filename='profile.prof')

    # @profile
    def get_calc_save(self, snapshot, url, index, total, job_id):
        if index == 100:
            allSizes = []
            for obj in locals().values():
                allSizes.append(asizeof.asizeof(obj) / 1024)
            rdb.set_trace()
        if snapshot[1] in self.digest_dict:
            self.save_to_redis(url, snapshot, self.digest_dict[snapshot[1]], total, index)
        else:
            data = self.download_snapshot(snapshot, url, index, total, job_id)
            if data is not None:
                data = self.calc_features(data)
                simhash = self.calculate_simhash(data)
                data = None
                self.digest_dict[snapshot[1]] = simhash
                self.save_to_redis(url, snapshot, simhash, total, index)
                simhash = None
                gc.collect()
                self._log.info('size of data: ' + str(sys.getsizeof(data)))
                self._log.info('size of simhash: ' + str(sys.getsizeof(simhash)))
                self._log.info('size of self.digest_dict: ' + str(sys.getsizeof(self.digest_dict)))
                self._log.info('size of self.redis_db: ' + str(sys.getsizeof(self.redis_db)))

    def calc_features(self, response):
        soup = BeautifulSoup(response.data.decode('utf-8', 'ignore'))

        # kill all script and style elements
        for script in soup(["script", "style"]):
            script.extract()  # rip it out

        # get text
        text = soup.get_text()
        soup = None
        # turn all characters to lowercase
        text = text.lower()
        # break into lines and remove leading and trailing space on each
        lines = (line.strip() for line in text.splitlines())
        # break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # drop blank lines
        text = '\n'.join(chunk for chunk in chunks if chunk)

        text = text.split()

        text = {k: sum(1 for _ in g) for k, g in groupby(sorted(text))}

        return text

    def calculate_simhash(self, text):
        temp_simhash = Simhash(text, self.simhash_size, hashfunc=hash_function).value
        # self._log.info(temp_simhash)
        return temp_simhash

    def run(self, url, year):
        time_started = datetime.datetime.now()
        # self._log.info('calculate simhash started')
        if not url:
            # self._log.error('did not give url parameter')
            result = {'status': 'error', 'info': 'URL is required.'}
        elif not year:
            # self._log.error('did not give year parameter')
            result = {'status': 'error', 'info': 'Year is required.'}
        else:
            try:
                # self._log.info('fetching timestamps of %s for year %s', url, year)
                self.update_state(state='PENDING',
                                  meta={'info': 'Fetching timestamps of '
                                                + url + ' for year ' + year})
                wayback_url = 'http://web.archive.org/cdx/search/cdx?url=' + url + \
                              '&' + 'from=' + year + '&to=' + year + '&fl=timestamp,digest&output=json'
                if self.snapshots_number != -1:
                    wayback_url += '&limit=' + str(self.snapshots_number)
                http = urllib3.PoolManager()
                response2 = http.request('GET', wayback_url)
                # self._log.info('finished fetching timestamps of %s for year %s', url, year)
                snapshots = json.loads(response2.data.decode('utf-8'))

                if not snapshots:
                    # self._log.error('no snapshots found for this year and url combination')
                    result = {'status': 'error',
                              'info': 'no snapshots found for this year and url combination'}
                    return json.dumps(result, sort_keys=True)
                snapshots.pop(0)
                total = len(snapshots)
                job_id = self.request.id
                with concurrent.futures.ThreadPoolExecutor(max_workers=
                                                           self.thread_number) as executor:
                    # Start the load operations and mark each future with its URL
                    # future_to_url = {executor.submit(self.start_profiling,
                    #                                  snapshot, url, index, total, job_id):
                    future_to_url = {executor.submit(self.get_calc_save,
                                                     snapshot, url, index, total, job_id):
                                         snapshot for index, snapshot in enumerate(snapshots)}
                    for future in concurrent.futures.as_completed(future_to_url):
                        try:
                            future.result()
                        except Exception as exc:
                            # self._log.error(exc)
                            return
            except Exception as exc:
                # self._log.error(exc.args[0])
                result = {'status': 'error', 'info': exc.args[0]}
                return json.dumps(result, sort_keys=True)
            time_ended = datetime.datetime.now()
            result = {'duration': str((time_ended - time_started).seconds)}
            # self._log.info('calculate simhash ended with duration: %d',
            #                (time_ended - time_started).seconds)
            return json.dumps(result, sort_keys=True)
        return json.dumps(result, sort_keys=True)

    def save_to_redis(self, url, snapshot, data, total, index):
        # self._log.info('saving to redis simhash for snapshot %d out of %d', index, total)
        self.redis_db.hset(surt(url), snapshot[0], base64.b64encode(struct.pack('L', data)))


def hash_function(x):
    return int(xxhash.xxh64(x).hexdigest(), 16)
