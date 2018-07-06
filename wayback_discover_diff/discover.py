from flask import (flash, jsonify)
import json
from simhash import Simhash
import redis
import datetime
import urllib3
from wayback_discover_diff.parallel_get import multi_get
from celery.contrib import rdb


class Discover():

    @staticmethod
    def simhash(url, timestamp):
        error = None
        if not url:
            error = 'URL is required.'
        elif not timestamp:
            error = 'Timestamp is required.'
        else:
            redis_db = redis.StrictRedis(host="localhost", port=6379, db=0)
            results = redis_db.get(url + timestamp)
            if results is not None:
                simhash_result = {'simhash': results.decode('utf-8')}
            else:
                simhash_result = {'simhash': 'None'}
        flash(error)
        simhash_result = json.dumps(simhash_result)
        return simhash_result

    def request_url(self, simhash_size, url, year):
        time_started = datetime.datetime.now()
        error = None
        if not url:
            result = 'URL is required.'
        elif not year:
            result = 'Year is required.'
        else:
            http = urllib3.PoolManager()
            r = http.request('GET', 'https://web.archive.org/cdx/search/cdx?url=' + url + '&'
                                                                                          'from=' + year + '&to=' + year + '&fl=timestamp&output=json&output=json&limit=30')
            try:
                snapshots = json.loads(r.data.decode('utf-8'))
                total = len(snapshots)
                if total == 0:
                    raise ValueError
                snapshots.pop(0)
                temp_snaps = []
                rdb.set_trace()
                for snapshot in snapshots:
                    temp_snaps.append(snapshot[0])
                    parallel_req = multi_get(temp_snaps, url, simhash_size)
                # redis_db = redis.StrictRedis(host="localhost", port=6379, db=0)
                # for i, snapshot in enumerate(snapshots):
                #     self.update_state(state='PENDING',
                #                       meta={'job_id': self.request.id,
                #                             'info': str(i) + ' out of ' + str(total) + ' captures have been processed',
                #                             })
                #
                #     r = http.request('GET', 'https://web.archive.org/web/' + snapshot[0] + '/' + url)
                #     temp_simhash = Simhash(r.data.decode('utf-8'), simhash_size).value
                #     redis_db.set(url + snapshot[0], temp_simhash)
            except (ValueError) as e:
                return json.dumps({'Message': 'Failed to fetch snapshots, please try again.'})
            time_ended = datetime.datetime.now()
            result = {'job_id': str(self.request.id), 'duration': str((time_ended - time_started).seconds)}
            return result
        return json.dumps(result)
