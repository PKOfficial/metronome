"""Metronome 'Job' System Integration Tests"""

import contextlib
import uuid
import time

from datetime import timedelta

import common
import shakedown
import pytest

from common import job_no_schedule, schedule
from dcos import metronome
from retrying import retry
from shakedown import dcos_version_less_than

pytestmark = [pytest.mark.skipif("dcos_version_less_than('1.8')")]


def test_add_job():
    client = metronome.create_client()
    with job(job_no_schedule()):
        job_id = job_no_schedule()['id']
        response = client.get_job(job_id)
        assert response.get('id') == job_id


def test_remove_job():
    client = metronome.create_client()
    client.add_job(job_no_schedule('remove-job'))
    assert client.remove_job('remove-job') is None
    job_exists = False
    try:
        client.get_job('remove-job')
        job_exists = True
    except:
        pass
    assert not job_exists, "Job exists"


def test_list_jobs():
    client = metronome.create_client()
    with job(job_no_schedule('job1')):
        with job(job_no_schedule('job2')):
            jobs = client.get_jobs()
            assert len(jobs) == 2


def test_update_job():
    client = metronome.create_client()
    job_json = job_no_schedule('update-job')
    with job(job_json):
        assert client.get_job('update-job')['description'] == 'electrifying rodent'

        job_json['description'] = 'updated description'
        client.update_job('update-job', job_json)
        assert client.get_job('update-job')['description'] == 'updated description'


def test_add_schedule():
    client = metronome.create_client()
    with job(job_no_schedule('schedule')):
        client.add_schedule('schedule', schedule())
        assert client.get_schedule('schedule', 'nightly')['cron'] == '20 0 * * *'


def test_disable_schedule():
    """ Confirms that a schedule runs when enabled but then stops firing
        when the schedule is disabled.
    """
    client = metronome.create_client()
    job_id = 'schedule-disabled-{}'.format(uuid.uuid4().hex)
    job_json = job_no_schedule(job_id)
    with job(job_json):
        # indent
        job_schedule = schedule()
        job_schedule['cron'] = '* * * * *'  # every minute
        client.add_schedule(job_id, job_schedule)

        # sleep until we run
        time.sleep(timedelta(minutes=1.1).total_seconds())
        runs = client.get_runs(job_id)
        run_count = len(runs)
        # there is a race condition where this could be 1 or 2
        # both are ok... what matters is that after disabled, that there are
        # no more
        assert run_count > 0

        # update enabled = False
        job_schedule['enabled'] = False
        client.update_schedule(job_id, 'nightly', job_schedule)

        # wait for the next run
        time.sleep(timedelta(minutes=1.5).total_seconds())
        runs = client.get_runs(job_id)
        # make sure there are no more than the original count
        assert len(runs) == run_count


def test_disable_schedule_recovery_from_master_bounce():
    """ Confirms that a schedule runs when enabled but then stops firing
        when the schedule is disabled.
    """
    client = metronome.create_client()
    job_id = 'schedule-disabled-{}'.format(uuid.uuid4().hex)
    job_json = job_no_schedule(job_id)
    with job(job_json):
        # indent
        job_schedule = schedule()
        job_schedule['cron'] = '* * * * *'  # every minute
        client.add_schedule(job_id, job_schedule)

        # sleep until we run
        time.sleep(timedelta(minutes=1.1).total_seconds())
        runs = client.get_runs(job_id)
        run_count = len(runs)
        # there is a race condition where this could be 1 or 2
        # both are ok... what matters is that after disabled, that there are
        # no more
        assert run_count > 0

        # update enabled = False
        job_schedule['enabled'] = False
        client.update_schedule(job_id, 'nightly', job_schedule)

        # # bounce master
        shakedown.restart_master_node()
        common.wait_for_mesos_endpoint(timedelta(minutes=10).total_seconds())

        # wait for the next run
        time.sleep(timedelta(minutes=1.5).total_seconds())
        runs = client.get_runs(job_id)
        # make sure there are no more than the original count
        assert len(runs) == run_count


def test_update_schedule():
    client = metronome.create_client()
    with job(job_no_schedule('schedule')):
        client.add_schedule('schedule', schedule())
        assert client.get_schedule('schedule', 'nightly')['cron'] == '20 0 * * *'
        schedule_json = schedule()
        schedule_json['cron'] = '10 0 * * *'
        client.update_schedule('schedule', 'nightly', schedule_json)
        assert client.get_schedule('schedule', 'nightly')['cron'] == '10 0 * * *'


def test_run_job():
    client = metronome.create_client()
    job_id = uuid.uuid4().hex
    with job(job_no_schedule(job_id)):
        runs = client.get_runs(job_id)
        assert len(runs) == 0

        client.run_job(job_id)
        time.sleep(2)
        assert len(client.get_runs(job_id)) == 1


def test_get_job_run():
    client = metronome.create_client()
    job_id = uuid.uuid4().hex
    with job(job_no_schedule(job_id)):
        client.run_job(job_id)
        time.sleep(2)
        run_id = client.get_runs(job_id)[0]['id']
        run = client.get_run(job_id, run_id)
        assert run['id'] == run_id
        assert run['status'] in ['ACTIVE', 'INITIAL']


def test_stop_job_run():
    client = metronome.create_client()
    job_id = uuid.uuid4().hex
    with job(job_no_schedule(job_id)):
        client.run_job(job_id)
        time.sleep(2)
        assert len(client.get_runs(job_id)) == 1
        run_id = client.get_runs(job_id)[0]['id']
        client.kill_run(job_id, run_id)

        assert len(client.get_runs(job_id)) == 0


def test_remove_schedule():
    client = metronome.create_client()
    with job(job_no_schedule('schedule')):
        client.add_schedule('schedule', schedule())
        assert client.get_schedule('schedule', 'nightly')['cron'] == '20 0 * * *'
        client.remove_schedule('schedule', 'nightly')
        schedule_exists = False
        try:
            client.get_schedule('schedule', 'nightly')
            schedule_exists = True
        except:
            pass
        assert not schedule_exists, "Schedule exists"


def remove_jobs():
    client = metronome.create_client()
    for job in client.get_jobs():
        client.remove_job(job['id'], True)


def test_job_constraints():
    client = metronome.create_client()
    host = common.get_private_ip()
    job_id = uuid.uuid4().hex
    job_def = job_no_schedule(job_id)
    common.pin_to_host(job_def, host)
    with job(job_def):
        # on the same node 3x
        for i in range(3):
            client.run_job(job_id)
            time.sleep(2)
            assert len(client.get_runs(job_id)) == 1
            run_id = client.get_runs(job_id)[0]['id']

            @retry(wait_fixed=1000, stop_max_delay=5000)
            def check_tasks():
                task = get_job_tasks(job_id, run_id)[0]
                task_ip = task['statuses'][0]['container_status']['network_infos'][0]['ip_addresses'][0]['ip_address']
                assert task_ip == host

            client.kill_run(job_id, run_id)

        assert len(client.get_runs(job_id)) == 0


def test_docker_job():
    client = metronome.create_client()
    job_id = uuid.uuid4().hex
    job_def = job_no_schedule(job_id)
    common.add_docker_image(job_def)
    with job(job_def):
        client.run_job(job_id)
        time.sleep(2)
        assert len(client.get_runs(job_id)) == 1


def setup_module(module):
    agents = shakedown.get_private_agents()
    if len(agents) < 2:
        assert False, "Incorrect Agent count"
    remove_jobs()


@contextlib.contextmanager
def job(job_json):
    job_id = job_json['id']
    client = metronome.create_client()
    client.add_job(job_json)
    try:
        yield
    finally:
        client.remove_job(job_id, True)
