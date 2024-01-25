import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("CI"),
    reason="Only run integration tests in CI, unless forced with 'CI' env var",
)


def test_project_init(random_project_name):
    from jobflow_remote.config import ConfigManager

    cm = ConfigManager()
    assert len(cm.projects) == 1
    assert cm.projects[random_project_name]
    project = cm.get_project()
    assert len(project.workers) == 2


def test_paramiko_ssh_connection(job_controller, slurm_ssh_port):
    from paramiko import SSHClient
    from paramiko.client import WarningPolicy

    client = SSHClient()
    client.set_missing_host_key_policy(WarningPolicy)
    client.connect(
        "localhost",
        port=slurm_ssh_port,
        username="jobflow",
        password="jobflow",
        look_for_keys=False,
        allow_agent=False,
    )


def test_project_check(job_controller, capsys):
    from jobflow_remote.cli.project import check

    check(print_errors=True)
    captured = capsys.readouterr()
    assert not captured.err
    expected = [
        "✓ Worker test_local_worker",
        "✓ Worker test_remote_worker",
        "✓ Jobstore",
        "✓ Queue store",
    ]
    for line in expected:
        assert line in captured.out


@pytest.mark.parametrize(
    "worker",
    ["test_local_worker", "test_remote_worker"],
)
def test_submit_flow(worker, job_controller):
    from jobflow import Flow

    from jobflow_remote import submit_flow
    from jobflow_remote.jobs.runner import Runner
    from jobflow_remote.jobs.state import FlowState, JobState
    from jobflow_remote.testing import add

    add_first = add(1, 5)
    add_second = add(add_first.output, 5)

    flow = Flow([add_first, add_second])
    submit_flow(flow, worker=worker)

    runner = Runner()
    runner.run(ticks=10)

    assert len(job_controller.get_jobs({})) == 2
    job_1, job_2 = job_controller.get_jobs({})
    assert job_1["job"]["function_args"] == [1, 5]
    assert job_1["job"]["name"] == "add"

    output_1 = job_controller.jobstore.get_output(uuid=job_1["uuid"])
    assert output_1 == 6
    output_2 = job_controller.jobstore.get_output(uuid=job_2["uuid"])
    assert output_2 == 11
    assert (
        job_controller.count_jobs(state=JobState.COMPLETED) == 2
    ), f"Jobs not marked as completed, full job info:\n{job_controller.get_jobs({})}"
    assert (
        job_controller.count_flows(state=FlowState.COMPLETED) == 1
    ), f"Flows not marked as completed, full flow info:\n{job_controller.get_flows({})}"


@pytest.mark.parametrize(
    "worker",
    ["test_local_worker", "test_remote_worker"],
)
def test_submit_flow_with_dependencies(worker, job_controller):
    from jobflow import Flow

    from jobflow_remote import submit_flow
    from jobflow_remote.jobs.runner import Runner
    from jobflow_remote.jobs.state import FlowState, JobState
    from jobflow_remote.testing import add, write_file

    add_parent_1 = add(1, 1)
    add_parent_2 = add(2, 2)
    add_children = add(add_parent_1.output, add_parent_2.output)
    write = write_file(add_children.output)

    flow = Flow([add_parent_1, add_parent_2, add_children, write])
    submit_flow(flow, worker=worker)

    runner = Runner()
    runner.run(ticks=20)

    assert len(job_controller.get_jobs({})) == 4
    job_1, job_2, job_3, job_4 = job_controller.get_jobs({})
    assert job_1["job"]["function_args"] == [1, 1]

    output_1 = job_controller.jobstore.get_output(uuid=job_1["uuid"])
    assert output_1 == 2
    output_2 = job_controller.jobstore.get_output(uuid=job_2["uuid"])
    assert output_2 == 4

    output_3 = job_controller.jobstore.get_output(uuid=job_3["uuid"])
    assert output_3 == 6

    output_4 = job_controller.jobstore.get_output(uuid=job_4["uuid"])
    assert output_4 is None

    assert (
        job_controller.count_jobs(state=JobState.COMPLETED) == 4
    ), f"Jobs not marked as completed, full job info:\n{job_controller.get_jobs({})}"
    assert (
        job_controller.count_flows(state=FlowState.COMPLETED) == 1
    ), f"Flows not marked as completed, full flow info:\n{job_controller.get_flows({})}"


@pytest.mark.parametrize(
    "worker",
    ["test_local_worker", "test_remote_worker"],
)
def test_expected_failure(worker, job_controller):
    from jobflow import Flow

    from jobflow_remote import submit_flow
    from jobflow_remote.jobs.runner import Runner
    from jobflow_remote.jobs.state import FlowState, JobState
    from jobflow_remote.testing import always_fails

    job_1 = always_fails()
    job_2 = always_fails()

    flow = Flow([job_1, job_2])
    submit_flow(flow, worker=worker)

    assert job_controller.count_jobs({}) == 2
    assert len(job_controller.get_jobs({})) == 2
    assert job_controller.count_flows({}) == 1

    runner = Runner()
    runner.run(ticks=10)

    assert job_controller.count_jobs(state=JobState.FAILED) == 2
    assert job_controller.count_flows(state=FlowState.FAILED) == 1