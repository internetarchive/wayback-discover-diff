import os
from flask import (Flask, request, jsonify)
import yaml
from wayback_discover_diff.discover import Discover
from celery import Celery

# def create_app():
# create and configure the app
app = Flask(__name__, instance_relative_config=True)
app.config.from_mapping(
    SECRET_KEY='dev',
)
app.config.update(
    CELERY_BROKER_URL='redis://localhost:6379',
    CELERY_RESULT_BACKEND='redis://localhost:6379'
)

with open(os.environ['WAYBACK_DISCOVER_DIFF_CONF'], 'r') as ymlfile:
    cfg = yaml.load(ymlfile)
simhash_size = cfg['simhash']['size']

app.config.from_pyfile('config.py', silent=True)

# ensure  the instance folder exists
try:
    os.makedirs(app.instance_path)
except OSError:
    pass

# Initialize Celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)


@celery.task(name='app', bind=True)
def celery_calculate_simhash(self, url, year):
    task = Discover.request_url(self, simhash_size, url, year)
    return task


@app.route('/simhash')
def simhash():
    url = request.args.get('url')
    timestamp = request.args.get('timestamp')
    return Discover.simhash(url, timestamp)


@app.route('/calculate-simhash')
def request_url():
    url = request.args.get('url')
    year = request.args.get('year')
    return jsonify({'status': 'started', 'job_id': str(celery_calculate_simhash.apply_async(args=[url, year]))})

@app.route('/job')
def job_status():
    job_id = request.args.get('job_id')
    task = celery_calculate_simhash.AsyncResult(job_id)
    if task.state == 'PENDING':
        # job did not start yet
        response = {
            'status': task.state,
            'job_id': task.info.get('job_id', 0),
            'info': task.info.get('info', 1),
        }
    elif task.state != 'FAILURE':
        response = {
            'status': task.state,
            'job_id': task.info.get('job_id', 0),
            'duration': task.info.get('duration', 1)
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info),  # this is the exception raised
        }
    return jsonify(response)

if __name__ == '__main__':
    app.run(debug=True)
# return app